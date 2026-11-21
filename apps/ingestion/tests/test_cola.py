"""Watcher (carpeta vigilada) y worker (Redis Streams) con fakeredis."""

import os

import fakeredis
import pytest

from ingesta.cola import VISTOS, Watcher, Worker, latido


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_publica_solo_cuando_el_archivo_esta_estable(settings, redis):
    settings.inbox_dir.mkdir()
    w = Watcher(settings, redis)
    (settings.inbox_dir / "FAQ.md").write_text("# a", encoding="utf-8")
    assert w.escanear() == []  # primera vista: espera a que se estabilice
    publicados = w.escanear()
    assert [e["ruta"] for e in publicados] == ["FAQ.md"] and redis.xlen(settings.stream) == 1
    assert w.escanear() == [] and redis.xlen(settings.stream) == 1  # sin cambios: no republica


def test_t_detectado_es_el_momento_en_que_se_vio_el_archivo(settings, redis):
    from datetime import UTC, datetime, timedelta

    settings.inbox_dir.mkdir()
    t = [datetime(2026, 11, 21, 12, 0, tzinfo=UTC)]
    w = Watcher(settings, redis, reloj=lambda: t[0])
    (settings.inbox_dir / "FAQ.md").write_text("# a", encoding="utf-8")
    w.escanear()
    t[0] += timedelta(seconds=3)
    evento = w.escanear()[0]
    assert evento["t_detectado"] == "2026-11-21T12:00:00+00:00"  # no el momento de la publicación (12:00:03)


def test_archivo_que_sigue_cambiando_no_se_publica(settings, redis):
    settings.inbox_dir.mkdir()
    w = Watcher(settings, redis)
    ruta = settings.inbox_dir / "Doc.md"
    for i in range(3):
        ruta.write_text("x" * (i + 1), encoding="utf-8")
        assert w.escanear() == []
    assert len(w.escanear()) == 1


def test_modificacion_se_vuelve_a_publicar_e_ignora_no_soportados(settings, redis):
    (settings.inbox_dir / "sub").mkdir(parents=True)
    w = Watcher(settings, redis)
    ruta = settings.inbox_dir / "sub" / "Politica.docx"
    ruta.write_bytes(b"v1")
    (settings.inbox_dir / "foto.png").write_bytes(b"x")
    (settings.inbox_dir / "~$Politica.docx").write_bytes(b"x")
    w.escanear()
    assert [e["ruta"] for e in w.escanear()] == ["sub/Politica.docx"]
    ruta.write_bytes(b"version 2 mas larga")
    os.utime(ruta, ns=(1, 2_000_000_000_000_000_000))
    w.escanear()
    assert [e["ruta"] for e in w.escanear()] == ["sub/Politica.docx"]
    assert redis.xlen(settings.stream) == 2


def test_reinicio_del_watcher_no_reprocesa_lo_visto(settings, redis):
    settings.inbox_dir.mkdir()
    (settings.inbox_dir / "FAQ.md").write_text("# a", encoding="utf-8")
    w = Watcher(settings, redis)
    w.escanear()
    w.escanear()
    nuevo = Watcher(settings, redis)
    assert nuevo.escanear() == [] and nuevo.escanear() == [] and redis.hlen(VISTOS) == 1


def test_worker_procesa_y_confirma(settings, redis):
    procesados = []
    w = Worker(
        settings, redis, lambda ruta, **kw: procesados.append((ruta.name, kw)) or {"resultado": "indexado"}
    )
    w.asegurar_grupo()
    w.asegurar_grupo()  # idempotente (BUSYGROUP)
    redis.xadd(
        settings.stream, {"ruta": "FAQ.md", "t_detectado": "2026-11-21T12:00:00+00:00", "intento": "1"}
    )
    assert w.procesar_lote(bloqueo_ms=10) == 1
    assert procesados[0][0] == "FAQ.md" and procesados[0][1]["t_detectado"].year == 2026
    assert redis.xpending(settings.stream, settings.grupo)["pending"] == 0
    assert w.procesar_lote(bloqueo_ms=10) == 0


def test_worker_reintenta_y_luego_envia_a_fallidos(settings, redis):
    def falla(ruta, **kw):
        raise RuntimeError("pdf corrupto")

    w = Worker(settings, redis, falla)
    w.asegurar_grupo()
    redis.xadd(
        settings.stream, {"ruta": "Malo.pdf", "t_detectado": "2026-11-21T12:00:00+00:00", "intento": "1"}
    )
    for _ in range(settings.max_intentos):
        assert w.procesar_lote(bloqueo_ms=10) == 1
    fallidos = redis.xrange(settings.stream_fallidos)
    assert (
        len(fallidos) == 1 and fallidos[0][1]["intento"] == "4" and "pdf corrupto" in fallidos[0][1]["error"]
    )
    assert w.procesar_lote(bloqueo_ms=10) == 0


def test_latido_y_comando_salud(settings, monkeypatch):
    from ingesta import __main__ as cli

    monkeypatch.setenv("INGESTA_LATIDO_DIR", str(settings.latido_dir))
    monkeypatch.setattr("sys.argv", ["ingesta", "salud", "--rol", "worker"])
    assert cli.main() == 1  # sin latido
    latido(settings, "worker")
    assert cli.main() == 0
    monkeypatch.setattr("sys.argv", ["ingesta", "salud", "--rol", "worker", "--max-s", "-1"])
    assert cli.main() == 1  # latido viejo


def test_reencolar_fallidos(settings, redis):
    from ingesta.cola import reencolar_fallidos

    redis.xadd(
        settings.stream_fallidos,
        {"ruta": "audios/A.wav", "t_detectado": "x", "intento": "4", "error": "TypeError"},
    )
    assert reencolar_fallidos(settings, redis) == ["audios/A.wav"]
    assert redis.xlen(settings.stream_fallidos) == 0
    evento = redis.xrange(settings.stream)[0][1]
    assert evento["intento"] == "1" and "error" not in evento


def test_corte_de_redis_no_tumba_el_worker(settings, monkeypatch):
    from redis.exceptions import TimeoutError as RedisTimeout

    monkeypatch.setattr("ingesta.cola.time.sleep", lambda s: None)

    class RedisInestable:
        def xreadgroup(self, *a, **k):
            raise RedisTimeout("Timeout reading from socket")

    w = Worker(settings, RedisInestable(), lambda *a, **k: {})
    assert w.ciclo() == 0  # se registra y sigue; antes el proceso terminaba y el contenedor se reiniciaba


def test_ciclo_normal_deja_latido(settings, redis):
    w = Worker(settings, redis, lambda *a, **k: {"resultado": "indexado"})
    w.asegurar_grupo()
    w.procesar_lote = lambda: 0  # sin eventos
    assert w.ciclo() == 0 and (settings.latido_dir / "ingesta-worker.latido").is_file()


def test_error_inesperado_al_crear_grupo(settings):
    class RedisRoto:
        def xgroup_create(self, *a, **k):
            raise ConnectionError("redis caído")

    with pytest.raises(ConnectionError):
        Worker(settings, RedisRoto(), lambda *a, **k: {}).asegurar_grupo()
