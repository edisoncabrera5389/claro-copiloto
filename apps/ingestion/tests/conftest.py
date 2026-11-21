"""Fixtures: documentos sintéticos generados en la prueba (no son los insumos) y entorno en memoria."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mongomock
import pytest
from qdrant_client import QdrantClient

from ingesta.config import Settings
from ingesta.embeddings import EmbedderDeterminista
from ingesta.indice import IndiceQdrant
from ingesta.pii import Anonimizador
from ingesta.pipeline import Pipeline
from ingesta.registro import Registro

RAIZ = Path(__file__).resolve().parents[3]
RAW = RAIZ / "data" / "raw"
requiere_insumos = pytest.mark.skipif(
    not (RAW / "01_documentos").is_dir(), reason="Faltan los insumos en data/raw: scripts/bootstrap_data.py"
)


# ------------------------------------------------------------------ generadores de documentos ---


def crear_docx(ruta: Path, version: str = "3.1", titulo: str = "Política de Prueba") -> Path:
    import docx

    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = f"POL-PRU-2026 · Versión {version} · Uso interno"
    d.add_paragraph(titulo, style="Title")
    d.add_paragraph("1. Objetivo", style="Heading 1")
    d.add_paragraph("Definir las reglas de prueba para el asesor.")
    d.add_paragraph("2. Criterios", style="Heading 1")
    d.add_paragraph("Sin mora mayor a 30 días.", style="List Paragraph")
    t = d.add_table(rows=3, cols=3)
    for i, fila in enumerate(
        [
            ["Antigüedad", "Opción A", "Opción B"],
            ["Más de 24 meses", "30 %", "Upgrade"],
            ["Menos de 12 meses", "Repetidor", "Repetidor"],
        ]
    ):
        for j, v in enumerate(fila):
            t.cell(i, j).text = v
    d.add_paragraph("Texto después de la tabla en la misma sección.")
    d.save(ruta)
    return ruta


def crear_pdf(ruta: Path, version: str = "1.0", precio: str = "$89.900", paginas: int = 2) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for n in range(1, paginas + 1):
        pdf.add_page()
        pdf.cell(
            0, 8, f"CAT-2026 - Version {version} - Vigente desde 01/11/2026", new_x="LMARGIN", new_y="NEXT"
        )
        if n == 1:
            pdf.cell(0, 8, "Catalogo de Prueba", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 8, "1. Alcance", new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 6, "Planes de prueba. Pasos: 1. Conectese al modem.")
            pdf.cell(0, 8, "2. Internet Hogar", new_x="LMARGIN", new_y="NEXT")
            with pdf.table() as tabla:
                for fila in [
                    ["Plan", "Precio"],
                    ["Hogar Fibra 300", precio],
                    ["Hogar Fibra 500", "$109.900"],
                ]:
                    r = tabla.row()
                    for v in fila:
                        r.cell(v)
            pdf.cell(0, 8, "3. Movil", new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 6, "Claro Max 25 GB con WhatsApp sin consumo.")
        else:
            pdf.cell(0, 8, "4. Promociones", new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 6, "Promocion Fibra 500 solo para clientes nuevos.")
        pdf.cell(0, 8, f"DOCUMENTO FICTICIO - Pag. {n}", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(ruta))
    return ruta


def crear_pdf_imagen(ruta: Path) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 400), "white")
    ImageDraw.Draw(img).text((40, 40), "Documento escaneado", fill="black")
    img.save(ruta, "PDF", resolution=150)
    return ruta


def crear_eml(ruta: Path) -> Path:
    ruta.write_text(
        "From: Gerencia <gerencia@ejemplo.test>\nTo: equipo@ejemplo.test\nSubject: Recordatorio de prueba\n"
        "Date: Mon, 09 Nov 2026 08:15:00 -0500\nContent-Type: text/plain; charset=utf-8\n\n"
        "Equipo: escribir a ana.perez@correo.co o al 300 123 4567. Firma: Laura Gómez.\n",
        encoding="utf-8",
    )
    return ruta


def crear_transcripcion(ruta: Path, id_: str = "TRX-9001") -> Path:
    ruta.write_text(
        f"ID: {id_}\nFECHA: 2026-10-01T11:12\nCANAL: chat\nCIUDAD: Villavicencio\n---\n"
        "ASESOR: Bienvenido a Claro, habla con Marcela. ¿Con quién tengo el gusto?\n"
        "CLIENTE: Hola, con Juliana Mejía Martínez.\nASESOR: ¿Me confirma su documento?\n"
        "CLIENTE: Sí, es 359268319.\n"
        "CLIENTE: Mi celular es 312 527 3199.\n",
        encoding="utf-8",
    )
    return ruta


def crear_md(ruta: Path) -> Path:
    ruta.write_text(
        "# Preguntas frecuentes\n\n> Ficticio.\n\n## ¿Cómo pago?\n\nEn la app Mi Claro o por PSE.\n\n"
        "## Error E-202\n\nRefresque la señal desde la app Mi Claro.\n",
        encoding="utf-8",
    )
    return ruta


# ------------------------------------------------------------------------------ entorno -------


@pytest.fixture(scope="session")
def anonimizador() -> Anonimizador:
    return Anonimizador()  # spaCy tarda unos segundos: una vez por sesión


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(inbox_dir=tmp_path / "inbox", latido_dir=tmp_path, whisper_dir=tmp_path / "modelos")


@dataclass
class Entorno:
    pipeline: Pipeline
    indice: IndiceQdrant
    registro: Registro
    embedder: EmbedderDeterminista
    reloj: list


@pytest.fixture
def entorno(settings, anonimizador) -> Entorno:
    embedder = EmbedderDeterminista(64)
    indice = IndiceQdrant(QdrantClient(":memory:"), "conocimiento", 64)
    indice.asegurar()
    registro = Registro(mongomock.MongoClient()["copiloto"])
    registro.asegurar()
    t = [datetime(2026, 11, 21, 12, 0, tzinfo=UTC)]

    def reloj() -> datetime:
        t[0] += timedelta(milliseconds=100)
        return t[0]

    return Entorno(
        Pipeline(settings, indice, registro, embedder, anonimizador, reloj=reloj),
        indice,
        registro,
        embedder,
        t,
    )
