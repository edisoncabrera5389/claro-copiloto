"""Anonimización de PII (Ley 1581) con Presidio en español + reconocedores colombianos.

Hallazgos con los insumos que motivan el diseño:
- Presidio en español NO trae reconocedor de cédula colombiana: "Sí, es 359268319" pasaba intacto.
- spaCy marca "Claro" y "Villavicencio" como PERSONA y "ASESOR" como organización: se anonimiza solo
  PERSONA, con lista de exclusión (marcas, ciudades) y descartando etiquetas en mayúsculas.

Dos modos:
- `completo` (transcripciones, audios, correos): NER de personas + documento, celular y correo.
- `reglas` (catálogos, políticas, manuales, FAQ): solo expresiones regulares, sin NER, para no
  alterar contenido normativo con falsos positivos.
"""

import re
import unicodedata
from collections import Counter
from typing import Any

ETIQUETAS = {
    "PERSON": "<PERSONA>",
    "CO_DOCUMENTO": "<DOCUMENTO>",
    "CO_CELULAR": "<CELULAR>",
    "EMAIL_ADDRESS": "<CORREO>",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CELULAR = re.compile(r"(?<!\d)(?:\+?57[\s-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
# 6 a 10 dígitos o con puntos de miles; no después de $, letras o guion (montos, IDs, códigos).
_DOCUMENTO = re.compile(r"(?<![\w$.,-])(?:\d{1,3}(?:\.\d{3}){2,3}|\d{6,10})(?![\w.,]?\d)")
# Nombres presentados en el diálogo: "habla con Marcela", "Hola, con Juliana Mejía Martínez".
_NOMBRE_DIALOGO = re.compile(
    r"(?:habla con|[Hh]ola,? con|[Mm]i nombre es|[Ll]e habla|[Ss]oy)\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+(?:de\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3})"
)

NO_PERSONAS = {
    "claro",
    "mi claro",
    "claro video",
    "claro musica",
    "claro max",
    "decobox",
    "wifi",
    "asesor",
    "cliente",
    "hogar",
    "fibra",
    "triple play",
    "pse",
    "sic",
    "crc",
    "netflix",
    "whatsapp",
    "facebook",
    "instagram",
    "equipo",
    "firma",
    "asunto",
    "fecha",
    "gerencia",
    "saludos",
    "cordialmente",
    "atentamente",
    "estimados",
    # ciudades de Colombia (la ciudad sola no identifica a nadie y es útil para análisis)
    "bogota",
    "medellin",
    "cali",
    "barranquilla",
    "cartagena",
    "bucaramanga",
    "pereira",
    "manizales",
    "ibague",
    "villavicencio",
    "cucuta",
    "santa marta",
    "pasto",
    "neiva",
    "armenia",
    "monteria",
    "tunja",
    "popayan",
    "valledupar",
    "sincelejo",
    "riohacha",
    "quibdo",
    "florencia",
    "yopal",
    "chapinero",
    "soacha",
}


CONECTORES = {"de", "del", "la", "las", "los", "y"}
_PUNTUACION = ".,;:!?¿¡()\"'"


def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().strip()


def redactar_reglas(texto: str) -> tuple[str, Counter[str]]:
    conteo: Counter[str] = Counter()
    for rx, etiqueta in ((_EMAIL, "EMAIL_ADDRESS"), (_CELULAR, "CO_CELULAR"), (_DOCUMENTO, "CO_DOCUMENTO")):
        texto, n = rx.subn(ETIQUETAS[etiqueta], texto)
        conteo[etiqueta] += n
    return texto, +conteo


class Anonimizador:
    """El motor de spaCy se carga una vez (unos segundos) y se reutiliza."""

    def __init__(self, modelo_spacy: str = "es_core_news_md", umbral: float = 0.6):
        from presidio_analyzer import (
            AnalyzerEngine,
            EntityRecognizer,
            Pattern,
            PatternRecognizer,
            RecognizerResult,
        )
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        class NombreDialogo(EntityRecognizer):
            def load(self) -> None:  # noqa: D102
                pass

            def analyze(self, text: str, entities: list[str], nlp_artifacts: Any = None) -> list:  # noqa: D102
                return [
                    RecognizerResult("PERSON", m.start(1), m.end(1), 0.9)
                    for m in _NOMBRE_DIALOGO.finditer(text)
                ]

        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "es", "model_name": modelo_spacy}],
                # Solo interesan personas: lugares, organizaciones y MISC se ignoran
                # (menos ruido y menos falsos positivos).
                "ner_model_configuration": {
                    "model_to_presidio_entity_mapping": {"PER": "PERSON", "PERSON": "PERSON"},
                    "labels_to_ignore": ["MISC", "LOC", "ORG"],
                },
            }
        ).create_engine()
        self._motor = AnalyzerEngine(nlp_engine=nlp, supported_languages=["es"])
        registro = self._motor.registry
        registro.add_recognizer(
            PatternRecognizer(
                "CO_DOCUMENTO",
                name="CoDocumento",
                supported_language="es",
                patterns=[Pattern("documento", _DOCUMENTO.pattern, 0.65)],
                context=["documento", "cédula", "cedula", "cc", "identificación", "nit"],
            )
        )
        registro.add_recognizer(
            PatternRecognizer(
                "CO_CELULAR",
                name="CoCelular",
                supported_language="es",
                patterns=[Pattern("celular", _CELULAR.pattern, 0.7)],
            )
        )
        registro.add_recognizer(
            NombreDialogo(supported_entities=["PERSON"], supported_language="es", name="NombreDialogo")
        )
        self._umbral = umbral

    @staticmethod
    def _recortar(tramo: str) -> str:
        """Quita del final palabras excluidas y conectores: "Luisa de Claro" → "Luisa".

        Whisper transcribe "habla con Luisa de Claro": descartar el tramo entero por contener "Claro"
        dejaba el nombre del asesor sin anonimizar.
        """
        palabras = tramo.split()
        while palabras and _norm(palabras[-1].strip(_PUNTUACION)) in NO_PERSONAS | CONECTORES:
            palabras.pop()
        return " ".join(palabras).rstrip(_PUNTUACION)  # el punto final no es parte del nombre

    def _es_persona_valida(self, texto: str, siguiente: str = "") -> bool:
        if not texto or texto.isupper() or len(texto) < 3:
            return False
        if " " not in texto and siguiente.startswith(":"):  # "Equipo:", "Firma:" son etiquetas, no nombres
            return False
        palabras = texto.split()
        # Un nombre propio va en mayúsculas iniciales: descarta "Vivo en (Villavicencio)" que spaCy marca.
        if not all(p[0].isupper() or _norm(p) in CONECTORES for p in palabras):
            return False
        n = _norm(texto)
        return n not in NO_PERSONAS and not any(p in NO_PERSONAS for p in n.split())

    def anonimizar(self, texto: str, modo: str = "completo") -> tuple[str, Counter[str]]:
        if modo == "reglas":
            return redactar_reglas(texto)
        resultados = self._motor.analyze(
            texto, language="es", entities=list(ETIQUETAS), score_threshold=self._umbral
        )
        validos = []
        for r in resultados:
            if r.entity_type == "PERSON":
                recortado = self._recortar(texto[r.start : r.end])
                r.end = r.start + len(recortado)
                if not self._es_persona_valida(recortado, texto[r.end : r.end + 2]):
                    continue
            validos.append(r)
        # Resolver solapes: gana el tramo más largo (y con mayor puntaje); reemplazo de atrás hacia adelante.
        validos.sort(key=lambda r: (r.start, -(r.end - r.start), -r.score))
        elegidos, fin = [], -1
        for r in validos:
            if r.start >= fin:
                elegidos.append(r)
                fin = r.end
        conteo: Counter[str] = Counter()
        for r in reversed(elegidos):
            texto = texto[: r.start] + ETIQUETAS[r.entity_type] + texto[r.end :]
            conteo[r.entity_type] += 1
        # Red de seguridad: lo que el NER no vio pero las reglas sí.
        texto, extra = redactar_reglas(texto)
        return texto, conteo + extra
