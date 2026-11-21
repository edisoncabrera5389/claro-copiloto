from ingesta.dispersos import tokens, vector_consulta, vector_documento
from ingesta.fragmentacion import fragmentar
from ingesta.modelos import Bloque


def test_tabla_queda_completa_y_seccion_corta_en_un_fragmento():
    tabla = "| A | B |\n|---|---|\n" + "\n".join(f"| fila {i} | valor |" for i in range(40))
    f = fragmentar(
        [Bloque("Texto corto.", "1. Sección"), Bloque(tabla, "2. Tabla", 3, es_tabla=True)], max_chars=2000
    )
    assert [x.texto for x in f] == ["Texto corto.", tabla]
    assert (f[1].es_tabla, f[1].pagina, f[1].orden) == (True, 3, 1)


def test_tabla_enorme_se_parte_repitiendo_encabezado():
    tabla = "| A | B |\n|---|---|\n" + "\n".join(f"| fila {i:03d} | {'x' * 40} |" for i in range(100))
    partes = fragmentar([Bloque(tabla, "T", es_tabla=True)], max_chars=500)
    assert len(partes) > 1 and all(p.texto.startswith("| A | B |\n|---|---|") for p in partes)


def test_texto_largo_en_ventanas_con_solape():
    oraciones = [f"Oración número {i} con algo de contenido útil." for i in range(120)]
    f = fragmentar([Bloque(" ".join(oraciones), "S")], max_chars=800, solape=0.15)
    assert len(f) > 3 and all(len(x.texto) <= 800 for x in f)
    assert any(o in f[1].texto for o in f[0].texto.split(". ")[-2:])  # solape entre ventanas
    assert [x.orden for x in f] == list(range(len(f)))


def test_oracion_gigante_se_corta():
    f = fragmentar([Bloque("x" * 2500, None)], max_chars=1000)
    assert [len(x.texto) for x in f] == [1000, 1000, 500]


def test_tokens_conservan_codigos_siglas_y_montos():
    t = tokens("La luz LOS en rojo: error E-202, oferta RET-A por $109.900 (POL-RET-2026) y 500 Mbps.")
    for esperado in (
        "^los",
        "e-202",
        "202",
        "ret-a",
        "$109900",
        "109900",
        "pol-ret-2026",
        "500",
        "mbps",
        "rojo",
    ):
        assert esperado in t
    assert "la" not in t and "los" not in t and "en" not in t  # stopwords fuera, la sigla LOS dentro


def test_codigo_sin_guion_equivale_al_codigo_con_guion():
    assert tokens("el error E202") == ["error", "e-202", "202"]  # así lo transcribe Whisper
    assert set(tokens("E-202")) <= set(tokens("E202")) | {"e-202", "202"}


def test_normaliza_tildes_plurales_y_miles():
    assert tokens("Facturación facturas") == ["facturacion", "factura"]
    assert tokens("Ñandú 1.200.000") == ["ñandu", "1200000"]


def test_vectores_estables_y_consulta_binaria():
    i1, v1 = vector_documento("Hogar Fibra 300 Hogar")
    i2, _ = vector_documento("Hogar Fibra 300 Hogar")
    assert i1 == i2 == sorted(i1) and len(i1) == len(v1) == 3
    pesos = dict(zip(i1, v1, strict=True))
    iq, vq = vector_consulta("hogar")
    assert vq == [1.0] and pesos[iq[0]] > min(pesos.values())  # "hogar" (tf=2) pesa más que los demás
