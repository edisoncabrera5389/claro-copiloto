import pytest

from copiloto_mcp.pii import filtrar, redactar_texto


def test_filtrar_quita_campos_personales_a_cualquier_profundidad():
    dato = {
        "cliente_id": "C-1",
        "numero_documento": "123",
        "celular": "300",
        "email": "a@b.co",
        "titulares": [{"nombre": "X", "email": "x@y.co"}],
    }
    assert filtrar(dato) == {"cliente_id": "C-1", "titulares": [{"nombre": "X"}]}
    assert dato["email"] == "a@b.co"  # no muta el original


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Cliente con cédula 1023456789 reporta falla", "Cliente con cédula [DOCUMENTO] reporta falla"),
        ("CC 1.023.456.789 sin servicio", "CC [DOCUMENTO] sin servicio"),
        ("Llamar al 300 123 4567", "Llamar al [CELULAR]"),
        ("Celular +57 315-117-8371", "Celular [CELULAR]"),
        ("Correo ana.perez+1@correo-ficticio.co", "Correo [CORREO]"),
    ],
)
def test_redacta_documento_celular_y_correo(texto, esperado):
    assert redactar_texto(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "Ajuste de $150.000 por falla",
        "Compensación de $1.200.000 aprobada",
        "Relacionado con TK-990001 y C-1004",
        "Falla desde 2026-11-12 por 3 días",
        "Factura F-5003 por 89900",
    ],
)
def test_no_toca_montos_ids_ni_fechas(texto):
    assert redactar_texto(texto) == texto


def test_redaccion_es_idempotente():
    una = redactar_texto("CC 1023456789, cel 3001234567, mail a@b.co")
    assert redactar_texto(una) == una
