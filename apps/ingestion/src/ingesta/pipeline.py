"""Pipeline de un archivo: identificar → hash (idempotencia) → extraer → versión → PII → chunking →
embeddings + BM25 → Qdrant → vigencia → registro y frescura.

Reglas de versión y formato:
- Mismo hash ya procesado → `sin_cambios` (idempotente).
- Versión declarada en el contenido ("Versión 2.0") o en el nombre (_v2) manda.
- Sin versión declarada: otro FORMATO del mismo documento = misma versión (DOCX y PDF de una política);
  el MISMO formato con contenido distinto = versión siguiente.
- Misma versión en dos formatos: se indexa el más fiel (DOCX > PDF); el otro queda como alterno.
- Solo la versión más alta queda `vigente=true`; las anteriores se conservan para auditoría.
"""

import hashlib
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import models

from ingesta import dispersos, extractores
from ingesta.config import Settings
from ingesta.embeddings import Embedder
from ingesta.fragmentacion import fragmentar
from ingesta.identificacion import (
    PRIORIDAD_FORMATO,
    detectar_codigo,
    detectar_version,
    detectar_vigente_desde,
    identificar,
    siguiente_version,
    version_tupla,
)
from ingesta.indice import IndiceQdrant, id_punto
from ingesta.modelos import Bloque, DocumentoExtraido, Identidad
from ingesta.pii import Anonimizador
from ingesta.registro import Registro

MODO_PII = {"transcripcion": "completo", "correo": "completo"}  # el resto: solo reglas


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        indice: IndiceQdrant,
        registro: Registro,
        embedder: Embedder,
        anonimizador: Anonimizador,
        extraer: Callable[[Path, Identidad, Settings], DocumentoExtraido] = extractores.extraer,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.s, self.indice, self.registro = settings, indice, registro
        self.embedder, self.anonimizador, self._extraer, self._reloj = embedder, anonimizador, extraer, reloj

    def _cerrar(self, evento: dict[str, Any], resultado: str, **extra: Any) -> dict[str, Any]:
        t_fin = self._reloj()
        evento.update(
            resultado=resultado,
            t_fin=t_fin,
            duracion_s=round((t_fin - evento["t_inicio"]).total_seconds(), 3),
            **extra,
        )
        if resultado == "indexado":
            evento["frescura_s"] = round((t_fin - evento["t_detectado"]).total_seconds(), 3)
        self.registro.registrar_ingesta(evento)
        return evento

    @staticmethod
    def _decidir_version(doc: dict[str, Any] | None, ident: Identidad, explicita: str | None) -> str:
        if explicita:
            return explicita
        if doc is None:
            return "1.0"
        vigente = doc["version_vigente"]
        formatos = {v["formato"] for v in doc["versiones"] if v["version"] == vigente}
        formatos |= {a["formato"] for a in doc.get("alternos", []) if a["version"] == vigente}
        if ident.formato not in formatos:
            return vigente  # otro formato del mismo documento
        mayor = max((v["version"] for v in doc["versiones"]), key=version_tupla)
        return siguiente_version(mayor)  # mismo formato, contenido distinto

    def revertir(self, doc_id: str, version: str) -> dict[str, Any]:
        """Retira una versión: borra sus fragmentos y la vigencia vuelve a la versión anterior más alta."""
        self.indice.reemplazar_version(doc_id, version, [])
        nueva, fuentes = self.registro.revertir_version(doc_id, version)
        if nueva:
            self.indice.marcar_vigencia(doc_id, nueva)
        return {"doc_id": doc_id, "retirada": version, "vigente": nueva, "fuentes": fuentes}

    def procesar(
        self,
        ruta: Path,
        t_detectado: datetime | None = None,
        evento_id: str | None = None,
        forzar: bool = False,
    ) -> dict[str, Any]:
        """`forzar=True` reindexa aunque el hash ya se conozca (p. ej. tras mejorar la anonimización),
        conservando la misma versión."""
        t_inicio = self._reloj()
        evento: dict[str, Any] = {
            "evento_id": evento_id,
            "fuente": ruta.name,
            "t_detectado": t_detectado or t_inicio,
            "t_inicio": t_inicio,
        }
        ident = identificar(ruta)
        if ident is None:
            return self._cerrar(evento, "omitido", motivo="formato no soportado o archivo ignorado")
        evento.update(doc_id=ident.doc_id, tipo=ident.tipo, formato=ident.formato)
        if not ruta.is_file():
            return self._cerrar(evento, "omitido", motivo="el archivo ya no existe")
        hash_ = hashlib.sha256(ruta.read_bytes()).hexdigest()
        evento["hash"] = hash_
        if self.registro.hash_conocido(ident.doc_id, hash_) and not forzar:
            return self._cerrar(evento, "sin_cambios")

        extraido = self._extraer(ruta, ident, self.s)
        cabecera = f"{extraido.texto_cabecera}\n{extraido.texto[:4000]}"
        doc = self.registro.documento(ident.doc_id)
        mismo_contenido = next((v for v in doc["versiones"] if v["hash"] == hash_), None) if doc else None
        version = (
            mismo_contenido["version"]  # reproceso forzado: misma versión, no una nueva
            if mismo_contenido
            else self._decidir_version(doc, ident, detectar_version(cabecera, ruta.name))
        )
        previa = next((v for v in doc["versiones"] if v["version"] == version), None) if doc else None
        entrada = {"version": version, "hash": hash_, "formato": ident.formato, "fuente": ident.fuente}

        if (
            previa
            and previa["formato"] != ident.formato
            and (PRIORIDAD_FORMATO[previa["formato"]] >= PRIORIDAD_FORMATO[ident.formato])
        ):
            self.registro.guardar_alterno(ident.doc_id, {**entrada, "registrado": self._reloj()})
            return self._cerrar(evento, "formato_alterno", version=version, preferido=previa["fuente"])

        # PII antes de que el texto salga del proceso (embeddings, índice, registro).
        conteo_pii: Counter[str] = Counter()
        modo = MODO_PII.get(ident.tipo, "reglas")
        bloques: list[Bloque] = []
        for b in extraido.bloques:
            texto, c = self.anonimizador.anonimizar(b.texto, modo)
            conteo_pii += c
            bloques.append(Bloque(texto, b.seccion, b.pagina, b.es_tabla))
        titulo = extraido.titulo or ident.doc_id
        fragmentos = fragmentar(bloques, self.s.fragmento_chars, self.s.solape)

        vigente_actual = doc["version_vigente"] if doc else None
        es_vigente = vigente_actual is None or version_tupla(version) >= version_tupla(vigente_actual)
        codigo, vigente_desde = detectar_codigo(cabecera), detectar_vigente_desde(cabecera)
        ahora = self._reloj()
        textos = [
            f"{titulo} — {f.seccion}\n{f.texto}" if f.seccion else f"{titulo}\n{f.texto}" for f in fragmentos
        ]
        densos = self.embedder.embed(textos) if textos else []
        puntos = []
        for f, texto, denso in zip(fragmentos, textos, densos, strict=True):
            indices, valores = dispersos.vector_documento(texto)
            puntos.append(
                models.PointStruct(
                    id=id_punto(ident.doc_id, version, f.orden),
                    vector={"denso": denso, "bm25": models.SparseVector(indices=indices, values=valores)},
                    payload={
                        "doc_id": ident.doc_id,
                        "version": version,
                        "vigente": es_vigente,
                        "titulo": titulo,
                        "seccion": f.seccion,
                        "pagina": f.pagina,
                        "orden": f.orden,
                        "es_tabla": f.es_tabla,
                        "tipo": ident.tipo,
                        "servicio": ident.servicio,
                        "fuente": ident.fuente,
                        "formato": ident.formato,
                        "codigo": codigo,
                        "vigente_desde": vigente_desde,
                        "fecha_documento": extraido.metadatos.get("fecha"),
                        "hash_documento": hash_,
                        "fecha_indexado": ahora.isoformat(),
                        "embedding": self.embedder.nombre,
                        "disperso": dispersos.NOMBRE,
                        "texto": f.texto,
                    },
                )
            )
        self.indice.reemplazar_version(ident.doc_id, version, puntos)
        if es_vigente:
            self.indice.marcar_vigencia(ident.doc_id, version)

        entrada.update(
            fragmentos=len(puntos),
            codigo=codigo,
            vigente_desde=vigente_desde,
            fecha_indexado=ahora,
            pii=dict(conteo_pii),
            ocr_paginas=extraido.metadatos.get("ocr_paginas", []),
        )
        base = {"titulo": titulo, "tipo": ident.tipo, "servicio": ident.servicio}
        self.registro.guardar_version(ident.doc_id, base, entrada, version if es_vigente else vigente_actual)
        if previa and previa["formato"] != ident.formato:  # el formato anterior pasa a alterno
            self.registro.guardar_alterno(ident.doc_id, {**previa, "registrado": ahora})
        if ident.tipo == "transcripcion":
            texto_anon = "\n\n".join(b.texto for b in bloques)
            meta = {k: v for k, v in extraido.metadatos.items() if k != "id"} | {"fuente": ident.fuente}
            self.registro.guardar_transcripcion(ident.doc_id, texto_anon, meta, ahora)

        return self._cerrar(
            evento,
            "indexado",
            version=version,
            vigente=es_vigente,
            fragmentos=len(puntos),
            pii=dict(conteo_pii),
            ocr_paginas=extraido.metadatos.get("ocr_paginas", []),
            reemplaza_formato=previa["fuente"] if previa else None,
        )
