from copiloto_mcp.breaker import CircuitBreaker, EstadoCircuito


def test_ciclo_cerrado_abierto_semiabierto_cerrado():
    t = [0.0]
    b = CircuitBreaker(3, 30, reloj=lambda: t[0])
    for _ in range(2):
        b.registrar_falla()
    assert b.permite() and b.estado is EstadoCircuito.CERRADO
    b.registrar_falla()
    assert b.estado is EstadoCircuito.ABIERTO and not b.permite()
    assert b.resumen()["reintentar_en_s"] == 30

    t[0] = 29.9
    assert not b.permite()
    t[0] = 30.0
    assert b.permite() and b.estado is EstadoCircuito.SEMIABIERTO
    b.registrar_exito()
    assert b.estado is EstadoCircuito.CERRADO and b.fallas_consecutivas == 0


def test_falla_en_semiabierto_reabre():
    t = [0.0]
    b = CircuitBreaker(2, 10, reloj=lambda: t[0])
    b.registrar_falla()
    b.registrar_falla()
    t[0] = 10
    assert b.permite()
    b.registrar_falla()
    assert b.estado is EstadoCircuito.ABIERTO and b.aperturas == 2


def test_exito_reinicia_el_conteo():
    b = CircuitBreaker(3, 10)
    b.registrar_falla()
    b.registrar_falla()
    b.registrar_exito()
    b.registrar_falla()
    assert b.estado is EstadoCircuito.CERRADO
