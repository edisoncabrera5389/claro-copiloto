"""Registro de documentos, versiones, linaje y frescura en MongoDB."""

from datetime import datetime
from statistics import median
from typing import Any

from ingesta.identificacion import version_tupla


class Registro:
    def __init__(self, db: Any):
        self.documentos = db["documentos"]
        self.ingestas = db["ingestas"]
        self.transcripciones = db["transcripciones"]

    def asegurar(self) -> None:
        self.ingestas.create_index("doc_id")
        self.ingestas.create_index("t_detectado")

    def documento(self, doc_id: str) -> dict[str, Any] | None:
        return self.documentos.find_one({"_id": doc_id})

    def hash_conocido(self, doc_id: str, hash_: str) -> bool:
        return (
            self.documentos.count_documents(
                {"_id": doc_id, "$or": [{"versiones.hash": hash_}, {"alternos.hash": hash_}]}
            )
            > 0
        )

    def guardar_version(
        self, doc_id: str, base: dict[str, Any], entrada: dict[str, Any], version_vigente: str
    ) -> None:
        """Agrega (o reemplaza) la entrada de una versión y fija la versión vigente del documento."""
        self.documentos.update_one({"_id": doc_id}, {"$pull": {"versiones": {"version": entrada["version"]}}})
        self.documentos.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    **base,
                    "version_vigente": version_vigente,
                    "actualizado": entrada["fecha_indexado"],
                },
                "$push": {"versiones": entrada},
                "$setOnInsert": {"alternos": []},
            },
            upsert=True,
        )

    def guardar_alterno(self, doc_id: str, entrada: dict[str, Any]) -> None:
        self.documentos.update_one({"_id": doc_id}, {"$pull": {"alternos": {"fuente": entrada["fuente"]}}})
        self.documentos.update_one({"_id": doc_id}, {"$push": {"alternos": entrada}})

    def revertir_version(self, doc_id: str, version: str) -> tuple[str | None, list[str]]:
        """Quita una versión (y sus alternos). Devuelve (nueva versión vigente, fuentes retiradas)."""
        doc = self.documento(doc_id)
        if doc is None:
            return None, []
        fuentes = [v["fuente"] for v in doc["versiones"] if v["version"] == version]
        fuentes += [a["fuente"] for a in doc.get("alternos", []) if a.get("version") == version]
        restantes = [v["version"] for v in doc["versiones"] if v["version"] != version]
        nueva = max(restantes, key=version_tupla, default=None)
        self.documentos.update_one(
            {"_id": doc_id},
            {
                "$pull": {"versiones": {"version": version}, "alternos": {"version": version}},
                "$set": {"version_vigente": nueva},
            },
        )
        return nueva, fuentes

    def registrar_ingesta(self, evento: dict[str, Any]) -> None:
        self.ingestas.insert_one(dict(evento))

    def guardar_transcripcion(self, id_: str, texto: str, metadatos: dict[str, Any], fecha: datetime) -> None:
        """Texto ya anonimizado: insumo para resúmenes, clasificación y evaluación."""
        self.transcripciones.replace_one(
            {"_id": id_},
            {"_id": id_, "texto": texto, "metadatos": metadatos, "actualizado": fecha},
            upsert=True,
        )

    def frescura(self) -> dict[str, Any]:
        valores = sorted(
            e["frescura_s"]
            for e in self.ingestas.find({"resultado": "indexado"}, {"frescura_s": 1})
            if "frescura_s" in e
        )
        if not valores:
            return {"n": 0}
        p95 = valores[min(len(valores) - 1, round(0.95 * (len(valores) - 1)))]
        return {
            "n": len(valores),
            "p50_s": round(median(valores), 2),
            "p95_s": round(p95, 2),
            "max_s": round(valores[-1], 2),
            "meta_s": 900,
            "cumple": valores[-1] <= 900,
        }

    def resumen(self) -> list[dict[str, Any]]:
        return [
            {
                "doc_id": d["_id"],
                "tipo": d.get("tipo"),
                "version_vigente": d.get("version_vigente"),
                "versiones": [v["version"] for v in d.get("versiones", [])],
                "fuente_vigente": next(
                    (v["fuente"] for v in d.get("versiones", []) if v["version"] == d.get("version_vigente")),
                    None,
                ),
                "alternos": [a["fuente"] for a in d.get("alternos", [])],
            }
            for d in self.documentos.find({}, sort=[("_id", 1)])
        ]
