# Documentación

Documentación como código: los Markdown son la fuente; el PDF del SAD se genera a partir de ellos.

| Archivo | Contenido |
|---|---|
| `00_control_resumen.md` | Control del documento y resumen ejecutivo |
| `01_planteamiento.md` | Planteamiento del problema (capítulo 1) |
| `02_arquitectura.md` | Arquitectura de la solución y ADR (capítulo 2) |
| `03_gestion_proyecto.md` | Gestión del proyecto (capítulo 3) |
| `assets/` | Imágenes usadas por los documentos |
| `presentacion/` | PPT entregada, su PDF y el script que la genera |
| `build/build_sad.py` | Generador del PDF consolidado (SAD) |

## Generar el SAD en PDF

Requisitos: Python con `markdown`, `mermaid.min.js` (`npm i mermaid`) y Microsoft Edge o Chrome.

```bash
pip install markdown
python docs/build/build_sad.py --mermaid <ruta>/node_modules/mermaid/dist/mermaid.min.js
```

Salida en `docs/build/out/` (no versionada). Los glosarios de los capítulos 1 y 2 se consolidan en el capítulo 4.

## Generar la presentación

`presentacion/build_deck.js` usa `pptxgenjs`, `react-icons` y `sharp`:

```bash
npm i pptxgenjs react-icons react react-dom sharp
node docs/presentacion/build_deck.js
```

Opcional: la variable `APPLY_THEME` puede apuntar a un módulo que escriba la paleta en el tema del archivo; sin ella, la presentación se genera igual.
