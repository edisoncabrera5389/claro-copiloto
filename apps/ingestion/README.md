# Ingesta y automatización de fuentes

**Tecnología:** Python · Redis Streams  
**Fases del caso:** 5, 6  
**Estado:** pendiente

## Responsabilidades

- Watcher de `data/inbox` (equivale a Blob Storage + Event Grid en Azure)
- Extracción PDF/tablas, DOCX, EML, MD; OCR si no hay capa de texto; transcripción con faster-whisper
- Anonimización de PII con Presidio, chunking por sección/tabla, metadatos y versionado por hash
- Indexado híbrido en Qdrant y registro de linaje en MongoDB; métrica de frescura

## Pruebas

pytest con documentos de ejemplo
