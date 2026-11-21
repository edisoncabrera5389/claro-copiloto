"""Vector disperso tipo BM25 para la búsqueda híbrida (Qdrant aplica el IDF con Modifier.IDF).

Tokenizador propio en lugar del de un modelo: conserva los códigos que la búsqueda semántica pierde
(E-202, RET-A, POL-RET-2026, LOS, $109.900, 500 Mbps). El retriever debe usar ESTE mismo módulo para
las consultas; el nombre versionado (`NOMBRE`) se guarda en cada punto para detectar incompatibilidades.
"""

import re
import unicodedata
import zlib
from collections import Counter

NOMBRE = "bm25-codigos-v1"
K1, B, LARGO_PROMEDIO = 1.2, 0.75, 120.0

_STOPWORDS_TXT = """
a al algo ante antes como con contra cual cuando de del desde donde durante e el ella ellos en entre era es
esa ese eso esta este esto estos fue ha hace hacia han hasta hay la las le les lo los mas me mi muy ni no nos
o os otra otro para pero por porque que quien se sea segun ser si sin sobre son su sus tambien te tiene tu un
una uno unos y ya usted ustedes cada puede debe
"""
STOPWORDS = frozenset(_STOPWORDS_TXT.split())
_TOKEN = re.compile(r"\$\s?\d[\d.,]*|\d+(?:[.,]\d+)*|[a-z0-9ñ]+(?:-[a-z0-9ñ]+)+|[a-z0-9ñ]+")
# Siglas en mayúsculas (LOS, PON, WPS, SIC, CRC): token propio que no pasa por stopwords.
# Sin esto, "LOS" (Loss of Signal) se volvía el artículo "los" y se descartaba.
_SIGLA = re.compile(r"(?<![\w-])[A-ZÑ]{2,6}(?![\w-])")


def _normalizar(texto: str) -> str:
    texto = texto.lower().replace("ñ", "\x00")
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return texto.replace("\x00", "ñ")


def tokens(texto: str) -> list[str]:
    salida: list[str] = [f"^{s.lower()}" for s in _SIGLA.findall(texto)]
    for t in _TOKEN.findall(_normalizar(texto)):
        if t.startswith("$"):  # $109.900 → "$109900" y "109900"
            num = re.sub(r"[^\d]", "", t)
            salida += [f"${num}", num]
        elif re.fullmatch(r"\d+(?:[.,]\d+)+", t):  # 109.900 → "109900"
            salida.append(re.sub(r"[.,]", "", t))
        elif "-" in t:  # código: se conserva entero y por partes significativas
            salida.append(t)
            salida += [p for p in t.split("-") if len(p) > 1 and p not in STOPWORDS]
        elif m := re.fullmatch(r"([a-z]{1,4})(\d{2,5})", t):  # Whisper escribe "E202": = "E-202"
            salida += [f"{m.group(1)}-{m.group(2)}", m.group(2)]
        elif t not in STOPWORDS and (len(t) > 1 or t.isdigit()):
            salida.append(t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t)
    return salida


def _indice(token: str) -> int:
    return zlib.crc32(token.encode())  # estable entre procesos (hash() de Python no lo es)


def vector_documento(texto: str) -> tuple[list[int], list[float]]:
    conteo = Counter(tokens(texto))
    largo = sum(conteo.values()) or 1
    norm = K1 * (1 - B + B * largo / LARGO_PROMEDIO)
    pares = {_indice(t): tf * (K1 + 1) / (tf + norm) for t, tf in conteo.items()}
    indices = sorted(pares)
    return indices, [round(pares[i], 4) for i in indices]


def vector_consulta(texto: str) -> tuple[list[int], list[float]]:
    indices = sorted({_indice(t) for t in tokens(texto)})
    return indices, [1.0] * len(indices)
