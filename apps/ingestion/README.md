# Ingesta y automatización de fuentes

**Tecnología:** Python 3.12 · Redis Streams · Qdrant · MongoDB · pdfplumber · python-docx · Tesseract · faster-whisper · Presidio + spaCy · uv  
**Fases del caso:** 5, 6  
**Estado:** ✅ carpeta vigilada, extracción, OCR, ASR, PII, chunking, indexado híbrido, versionado y frescura

Pipeline event-driven que mantiene la base de conocimiento al día: un documento que cae en `data/inbox` queda buscable, versionado y con su linaje en segundos (meta del caso: ≤ 15 min).

```
data/inbox ──(watcher, polling 3 s)──► Redis Stream ingesta:eventos ──(worker, grupo de consumidores)──►
  identificar → SHA-256 (idempotencia) → extraer → versión → PII → chunking → embeddings + BM25 →
  Qdrant (vigente=true/false) → MongoDB (versiones, alternos, ingestas, transcripciones) → frescura
```

## Decisiones y hallazgos con los insumos

| Tema | Decisión |
|---|---|
| **Watcher por polling** | En Docker Desktop sobre Windows, los eventos inotify de carpetas montadas no llegan de forma confiable. Polling de 3 s y publicación solo cuando el archivo tiene tamaño y fecha estables en dos escaneos (no se leen archivos a medio copiar). Lo visto queda en Redis: un reinicio no reprocesa |
| **Idempotencia** | SHA-256 del archivo: el mismo contenido → `sin_cambios`. Reindexar una versión borra sus fragmentos previos (IDs `uuid5(doc_id, versión, orden)`) |
| **DOCX y PDF duplicados** | Las 6 políticas y contratos vienen en ambos formatos. Se indexa el **DOCX** (el golden lo cita) y el PDF queda como `formato_alterno` del mismo `doc_id`. Si llega primero el PDF, el DOCX lo reemplaza |
| **Versión en el encabezado del DOCX** | `CON-HOG-2026 · Versión 2.0` está en el header de página, que python-docx no devuelve en el cuerpo. Sin leerlo, DOCX y PDF parecían versiones distintas |
| **Versionado** | Manda la versión declarada en el documento (o `_v2` en el nombre). Sin versión: otro formato = misma versión; mismo formato con contenido distinto = versión siguiente. Solo la versión más alta queda `vigente=true`; las anteriores se conservan para auditoría |
| **Tablas** | Una tabla = un fragmento completo en Markdown (matriz de retención, tarifas, LED, códigos de error). Las de pdfplumber se limpian: celdas `None`, encabezados partidos ("Precio"/"mensual") y valores corridos; el texto dentro de la tabla no se duplica |
| **Secciones en PDF** | Líneas y tablas en orden vertical; un `N. Título` corta sección solo si sigue la numeración (los pasos "1. Conéctese…" no cortan). Encabezados y pies repetidos se eliminan |
| **PII** | Presidio en español **no detecta la cédula colombiana** y marca "Claro" y "Villavicencio" como persona. Reconocedores propios (documento, celular, nombres presentados en el diálogo), solo PERSONA del NER, lista de exclusión (marcas, ciudades, etiquetas "Equipo:") y regex como red de seguridad. **Cero fugas en las 50 transcripciones** (8 documentos, 7 celulares, 58 nombres). Catálogos y políticas: solo reglas, sin NER |
| **BM25 propio** | Tokenizador que conserva códigos (`E-202`, `RET-A`, `POL-RET-2026`, `$109.900`) y siglas: "LOS" (Loss of Signal) se descartaba como el artículo "los". IDF en Qdrant (`Modifier.IDF`). El retriever debe usar el mismo módulo (`dispersos.NOMBRE = bm25-codigos-v1`, guardado en cada punto) |
| **Transcripciones** | Indexadas anonimizadas con `tipo=transcripcion` (el retriever las excluye por defecto) y guardadas en Mongo para resúmenes y evaluación |
| **Frescura** | `t_indexado − t_detectado`, donde `t_detectado` es cuando el watcher **vio** el archivo por primera vez (incluye la espera de estabilidad). Se guarda por evento en `ingestas`; `estado` reporta p50, p95, máximo y si cumple la meta de 900 s. Medido: **4,8 s** para el catálogo v2; p50 41 s en la carga inicial de 72 archivos en cola |
| **Audios** | faster-whisper 1.2.1 decodifica con PyAV pasando `metadata_errors`, que PyAV 19 eliminó (`TypeError`). El WAV se decodifica con `wave` + numpy y se remuestrea a 16 kHz (los insumos vienen a 22.050 Hz). Whisper escribe "E202": el BM25 lo trata igual que "E-202" |
| **PII en audios** | Whisper transcribe "habla con Luisa **de Claro**": el nombre se recorta de la marca y se anonimiza ("<PERSONA> de Claro"); un tramo solo es persona si sus palabras van con mayúscula inicial ("Vivo en Villavicencio" no lo es) |
| **Resiliencia** | Reintentos por evento (3) y dead-letter `ingesta:fallidos`; `reintentar` los devuelve a la cola tras corregir la causa. Un corte de Redis se registra y el bucle sigue (el timeout de socket supera el bloqueo de `XREADGROUP`; con el valor por defecto de redis-py 8 el worker se reiniciaba) |

## Metadatos de cada fragmento (payload de Qdrant)

`doc_id`, `version`, `vigente`, `titulo`, `seccion`, `pagina`, `orden`, `es_tabla`, `tipo`, `servicio`, `fuente` (archivo que se cita), `formato`, `codigo` (CAT-2026, POL-RET-2026…), `vigente_desde`, `fecha_documento`, `hash_documento`, `fecha_indexado`, `embedding`, `disperso`, `texto`. Índices de payload en `doc_id`, `version`, `tipo`, `servicio` y `vigente`.

## Ejecución

```powershell
docker compose up -d --build ingesta-watcher ingesta-worker     # levanta también redis, mongo y qdrant
py -3.13 scripts/sembrar_inbox.py                               # carga inicial del corpus en data/inbox
docker compose logs -f ingesta-worker                           # progreso (una línea JSON por archivo)
docker compose exec ingesta-worker python -m ingesta estado     # versiones vigentes, alternos y frescura
docker compose exec ingesta-worker python -m ingesta buscar "precio Hogar Fibra 300"
```

**Demo de frescura** (06_actualizaciones/LEEME.md):

```powershell
docker compose exec ingesta-worker python -m ingesta buscar "cuánto cuesta el plan Hogar Fibra 300"   # v1.0: $89.900
py -3.13 scripts/sembrar_inbox.py --catalogo-v2       # llega la versión 2.0 a la carpeta vigilada
docker compose logs -f ingesta-worker                 # "version": "2.0", "frescura_s": ~5
docker compose exec ingesta-worker python -m ingesta buscar "cuánto cuesta el plan Hogar Fibra 300"   # v2.0: $84.900
py -3.13 scripts/sembrar_inbox.py --quitar-v2         # ensayo: vuelve a vigente la v1.0 para repetir
```

Operación: `python -m ingesta reintentar` (dead-letter → cola), `procesar --forzar <archivo>` (reindexa la misma versión tras mejorar el pipeline), `revertir <doc_id> <versión>` (retira una versión y devuelve la vigencia a la anterior). Panel de Qdrant: http://localhost:6333/dashboard.

Variables (`INGESTA_*`, ver [config.py](src/ingesta/config.py)): `OPENAI_API_KEY` (embeddings; `OPENAI_BASE_URL` permite apuntar a LiteLLM), `EMBEDDING_MODEL`, `INGESTA_POLL_S`, `INGESTA_WHISPER_MODELO` (`small` por defecto), `INGESTA_FRAGMENTO_CHARS`, `INGESTA_SOLAPE`, `INGESTA_MAX_INTENTOS`.

Contenedores: imagen multi-stage (**1,65 GB**: Tesseract `spa`, spaCy, faster-whisper), usuario `10001`, `HEALTHCHECK` por latido, raíz de solo lectura y sin capacidades; `data/inbox` montada **solo lectura**. El modelo de Whisper se descarga la primera vez al volumen `modelos`. Redis 8, MongoDB 7 y Qdrant 1.20 con volúmenes persistentes y puertos solo en `127.0.0.1`.

**Resultado con el corpus real** (embeddings de OpenAI): 13 documentos de conocimiento + 53 transcripciones (50 TXT + 3 audios), 6 PDF como alternos, 123 fragmentos vigentes, 0 eventos fallidos. La búsqueda híbrida devuelve las fuentes del golden: "luz LOS en rojo" → manual del módem (tabla LED) + Política de Escalamiento (GQ-18); "error E-202" → FAQ + manual del decodificador + correo de refresco de señal (GQ-21); "Chapinero 12 de noviembre" → correo del incidente (GQ-24).

## Métricas (Prometheus)

El worker expone `http://ingesta-worker:9101/metrics` (red interna) con la librería estándar, sin dependencias nuevas que obliguen a reconstruir la imagen pesada: documentos por resultado, errores, **frescura** (histograma y último documento; meta ≤ 15 min, alerta `FrescuraDeIngesta`), eventos pendientes en la cola y en la dead-letter. La frescura aparece con el primer documento indexado tras el arranque (p. ej. el catálogo v2 de la demo).

## Pruebas

```powershell
cd apps/ingestion
uv run pytest                    # 91 pruebas: sintéticas + corpus real si hay insumos (cobertura 98 %)
uv run ruff check . ; uv run ruff format --check .
```

- **Sintéticas** (generan DOCX, PDF con tabla, PDF escaneado, EML, MD y TXT en la prueba; aptas para CI): identificación, extractores (OCR y Whisper inyectados), PII, chunking, BM25, pipeline (idempotencia, formatos, versiones, vigencia, linaje, frescura) con Qdrant en memoria y mongomock, watcher y worker con fakeredis (estabilidad, reintentos, dead-letter).
- **Corpus real** (`data/raw`, se omite si falta): 63 indexados + 6 alternos, versiones leídas del documento, matriz de retención completa, **cero fugas de PII en las 50 transcripciones** y llegada del catálogo v2.
