"""Guardrails determinísticos (antes y después del LLM).

Entrada: escalamiento obligatorio de la Política de Escalamiento (numeral 2), prompt injection y PII.
Salida: validación de citas [n] y red de seguridad de PII. El LLM no decide si se escala: lo decide
este código, y queda auditado con el motivo.
"""

import re
from dataclasses import dataclass

from copiloto_api.pii import Boveda

# (código, descripción para el asesor, patrón). Orden = prioridad.
ESCALAMIENTO = [
    (
        "ACCION_LEGAL",
        "acciones legales o quejas ante entes de control (tutela, demanda, denuncia, SIC o CRC)",
        # "demanda" solo en contexto legal: "la demanda de velocidad" no debe escalar.
        r"\btutela|\bdemandar(é|á|emos)?\b|(poner|interponer|una|la) demanda (judicial|legal|contra)|"
        r"\bdenuncia|\babogad|superintendencia|\bSIC\b|\bCRC\b|acci[oó]n legal",
    ),
    (
        "VULNERABILIDAD",
        "una situación de vulnerabilidad",
        r"discapacidad|adulto mayor|tercera edad|emergencia m[eé]dica|ox[ií]geno|silla de ruedas|"
        r"depende (del|de este) servicio|vive solo|est[aá] enferm",
    ),
    (
        "AGRESION",
        "amenazas o lenguaje agresivo",
        r"\bte voy a\b|\blos voy a\b|amenaz|\bmatar\b|hijueputa|malparid|gonorrea|\bimb[eé]cil|\bidiota",
    ),
    (
        "FRAUDE",
        "sospecha de fraude o suplantación de identidad",
        r"fraude|suplant|robaron (mi|la) identidad|a mi nombre sin|"
        r"no (he )?solicit[eé] .{0,30}(l[ií]nea|servicio)|"
        r"clonaron|estafa",
    ),
    (
        "TERCEROS",
        "una solicitud de datos de un tercero (no titular)",
        r"(datos|informaci[oó]n|factura|saldo|n[uú]mero|direcci[oó]n|plan) (de|del) (mi |su )?"
        r"(espos[oa]|herman[oa]|vecin[oa]|hij[oa]|mam[aá]|pap[aá]|novi[oa]|"
        r"otra persona|otro cliente|un tercero)",
    ),
]

INYECCION = re.compile(
    r"(ignora|olvida|omite) (todas )?(las |tus )?(instrucciones|reglas)|system prompt|prompt del sistema|"
    r"revela (tu|el|tus) (prompt|instrucciones)|act[uú]a como|modo (desarrollador|dios|sin restricciones)|"
    r"jailbreak|sin filtros",  # ojo: "DAN" no, con IGNORECASE bloquearía el verbo "dan"
    re.IGNORECASE,
)
_CLIENTE = re.compile(r"\bC-\d{4}\b", re.IGNORECASE)
_CITA = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Analisis:
    ruta: str  # agente | escalar | bloqueado
    motivo: str | None = None
    detalle: str | None = None
    mensaje_llm: str = ""
    cliente_id: str | None = None


def analizar_entrada(mensaje: str, boveda: Boveda) -> Analisis:
    cliente = _CLIENTE.search(mensaje)
    cliente_id = cliente.group(0).upper() if cliente else None
    if INYECCION.search(mensaje):
        return Analisis(
            "bloqueado",
            "PROMPT_INJECTION",
            "intento de modificar las instrucciones del asistente",
            cliente_id=cliente_id,
        )
    mensaje_llm = boveda.enmascarar(mensaje)
    for codigo, descripcion, patron in ESCALAMIENTO:
        if re.search(patron, mensaje, re.IGNORECASE):
            return Analisis("escalar", codigo, descripcion, mensaje_llm, cliente_id)
    return Analisis("agente", None, None, mensaje_llm, cliente_id)


def validar_citas(respuesta: str, n_fuentes: int) -> tuple[str, set[int], list[int]]:
    """Quita citas a fuentes inexistentes (referencia alucinada). Devuelve (texto, citadas, inválidas)."""
    citadas: set[int] = set()
    invalidas: list[int] = []

    def revisar(m: re.Match) -> str:
        numeros = [int(x) for x in re.split(r"\s*,\s*", m.group(1))]
        validos = [n for n in numeros if 1 <= n <= n_fuentes]
        invalidas.extend(n for n in numeros if n not in validos)
        citadas.update(validos)
        return "".join(f"[{n}]" for n in validos)

    return _CITA.sub(revisar, respuesta), citadas, invalidas
