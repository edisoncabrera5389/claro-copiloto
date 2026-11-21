"""Genera el Documento de Arquitectura de Solución (SAD) en PDF desde los Markdown de docs/.

Uso:
    python build_sad.py --mermaid <ruta a mermaid.min.js> [--browser <msedge|chrome>]

Requiere: pip install markdown · mermaid.min.js (npm i mermaid) · Edge o Chrome (headless).
"""
import argparse
import html
import re
import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]          # raíz del repositorio
DOCS = ROOT / "docs"
OUT_DIR = DOCS / "build" / "out"
ASSETS = DOCS / "assets"
VERSION = "1.0"
FECHA = "21 de noviembre de 2026"


def split_section(md: str, heading_regex: str):
    """Separa el texto desde el encabezado indicado hasta el final del archivo."""
    m = re.search(heading_regex, md, flags=re.M)
    if not m:
        return md, ""
    return md[: m.start()].rstrip() + "\n", md[m.end():].strip() + "\n"


def demote(md: str, levels: int = 1) -> str:
    return re.sub(r"^(#+) ", lambda m: "#" * (len(m.group(1)) + levels) + " ", md, flags=re.M)


def build_markdown() -> str:
    control = (DOCS / "00_control_resumen.md").read_text(encoding="utf-8")
    plan = (DOCS / "01_planteamiento.md").read_text(encoding="utf-8")
    arq = (DOCS / "02_arquitectura.md").read_text(encoding="utf-8")
    gest = (DOCS / "03_gestion_proyecto.md").read_text(encoding="utf-8")

    plan, glos_neg = split_section(plan, r"^## 1\.12 Glosario\s*$")
    arq, glos_tec = split_section(arq, r"^## 2\.17 Glosario técnico\s*$")
    glos_tec = re.sub(r"^> Términos de negocio.*\n", "", glos_tec, flags=re.M)

    glosario = (
        "# 4. Glosario\n\n"
        "## 4.1 Negocio y conceptos de IA\n\n" + demote(glos_neg, 0) + "\n"
        "## 4.2 Términos técnicos\n\n" + demote(glos_tec, 0) + "\n"
    )
    return "\n\n".join([control, plan, arq, gest, glosario])


def to_html(md_text: str, mermaid_js: Path) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": lambda v, s: re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")}},
    )
    # bloques mermaid → <pre class="mermaid">
    body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: f'<div class="diagram"><pre class="mermaid">{m.group(1)}</pre></div>',
        body,
        flags=re.S,
    )
    # imágenes relativas a docs/ → rutas absolutas (el HTML se genera en docs/build/out)
    body = body.replace('src="assets/', f'src="{ASSETS.as_uri()}/')
    # diagramas anchos marcados con <!-- landscape: título --> → página horizontal
    body = re.sub(
        r'<!-- landscape: (.*?) -->\s*<div class="diagram">',
        lambda m: f'<div class="diagram landscape"><div class="cap">{m.group(1)}</div>',
        body,
    )
    body = re.sub(
        r'<!-- landscape: (.*?) -->\s*<p>(<img [^>]+>)</p>',
        lambda m: f'<div class="diagram landscape"><div class="cap">{m.group(1)}</div>{m.group(2)}</div>',
        body,
    )
    # tabla de contenido (h1 y h2)
    toc_items = []
    for level, hid, title in re.findall(r'<h([12]) id="([^"]+)">(.*?)</h\1>', body):
        clean = re.sub(r"<[^>]+>", "", title)
        toc_items.append(f'<li class="toc-l{level}"><a href="#{hid}">{clean}</a></li>')
    toc = '<section class="toc"><h1 class="toc-title">Contenido</h1><ol>' + "".join(toc_items) + "</ol></section>"

    logo_w = (ASSETS / "logo-claro-blanco.png").as_uri()
    cover = f"""
<section class="cover">
  <img class="cover-logo" src="{logo_w}" alt="Logo Claro">
  <div class="cover-main">
    <div class="cover-kicker">Documento de Arquitectura de Solución (SAD)</div>
    <div class="cover-title">Claro Copiloto</div>
    <div class="cover-sub">Asistente de IA generativa para atención y retención<br>Planteamiento · Arquitectura · Gestión del proyecto</div>
  </div>
  <div class="cover-meta">
    <b>Prueba técnica · Líder Técnico AI Senior</b><br>
    Edison Cabrera · {FECHA} · Versión {VERSION}<br>
    <span>Todos los datos del caso son sintéticos</span>
  </div>
</section>"""

    css = f"""
@page {{ size: A4; margin: 18mm 16mm 18mm 16mm;
  @bottom-left {{ content: "Claro Copiloto · SAD v{VERSION}"; font: 8pt Calibri, Arial; color: #8C939F; }}
  @bottom-right {{ content: "Página " counter(page) " de " counter(pages); font: 8pt Calibri, Arial; color: #8C939F; }}
}}
@page :first {{ margin: 0; @bottom-left {{ content: none; }} @bottom-right {{ content: none; }} }}
@page wide {{ size: A4 landscape; margin: 12mm 14mm 14mm 14mm; }}
.landscape {{ page: wide; margin: 0; }}
.landscape .cap {{ font-weight: 700; font-size: 13pt; color: #DA291C; text-align: left; margin-bottom: 3mm; }}
.landscape svg {{ max-height: 165mm !important; }}
.landscape img {{ width: 100%; max-height: 172mm; object-fit: contain; border: 0.4pt solid #E2E4E8; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Calibri, Arial, sans-serif; font-size: 10.5pt; color: #1A1D29; line-height: 1.38; margin: 0; }}
.cover {{ height: 297mm; width: 210mm; background: #1A1D29; color: #fff; padding: 28mm 22mm; position: relative; page-break-after: always; }}
.cover-logo {{ width: 62mm; }}
.cover-main {{ position: absolute; top: 105mm; left: 22mm; right: 22mm; }}
.cover-kicker {{ color: #DA291C; font-weight: 700; font-size: 13pt; letter-spacing: .5px; text-transform: uppercase; }}
.cover-title {{ font-size: 44pt; font-weight: 700; margin: 4mm 0; }}
.cover-sub {{ font-size: 15pt; color: #D7DAE0; }}
.cover-meta {{ position: absolute; bottom: 28mm; left: 22mm; font-size: 11pt; color: #D7DAE0; }}
.cover-meta span {{ color: #8C939F; font-style: italic; }}
.toc {{ page-break-after: always; }}
.toc ol {{ list-style: none; padding: 0; }}
.toc li {{ line-height: 1.22; }}
.toc-l1 {{ font-weight: 700; margin-top: 2.2mm; font-size: 11pt; }}
.toc-l2 {{ margin-left: 7mm; font-size: 9.5pt; }}
.toc a {{ color: #1A1D29; text-decoration: none; }}
h1 {{ color: #DA291C; font-size: 22pt; margin: 0 0 4mm; page-break-before: always; }}
.toc-title, h1#control-del-documento {{ page-break-before: avoid; }}
h2 {{ font-size: 14pt; color: #1A1D29; margin: 7mm 0 2mm; page-break-after: avoid; }}
h3 {{ font-size: 11.5pt; color: #3D4A5C; margin: 5mm 0 2mm; page-break-after: avoid; }}
p, li {{ orphans: 3; widows: 3; }}
blockquote {{ margin: 3mm 0; padding: 2mm 4mm; background: #F3F4F6; border-radius: 2mm; color: #3D4A5C; }}
blockquote p {{ margin: 1mm 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 3mm 0 4mm; font-size: 9pt; page-break-inside: auto; }}
thead {{ display: table-header-group; }}
tr {{ page-break-inside: avoid; }}
th {{ background: #3D4A5C; color: #fff; text-align: left; padding: 1.6mm 2mm; font-weight: 700; }}
td {{ border-bottom: 0.4pt solid #E2E4E8; padding: 1.4mm 2mm; vertical-align: top; }}
tr:nth-child(even) td {{ background: #FAFAFB; }}
code {{ font-family: Consolas, monospace; font-size: 8.8pt; background: #F3F4F6; padding: 0 1mm; border-radius: 1mm; }}
th code {{ background: transparent; color: #fff; }}
.diagram {{ text-align: center; margin: 4mm 0; page-break-inside: avoid; }}
.diagram svg {{ max-width: 100% !important; height: auto; max-height: 215mm; }}
pre.mermaid {{ background: none; }}
a {{ color: #2A6F97; }}
"""

    mermaid_cfg = """
mermaid.initialize({ startOnLoad: false, theme: 'base', securityLevel: 'loose',
  themeVariables: { primaryColor: '#F3F4F6', primaryBorderColor: '#3D4A5C', primaryTextColor: '#1A1D29',
    lineColor: '#3D4A5C', secondaryColor: '#FDECEA', tertiaryColor: '#FFFFFF', fontFamily: 'Calibri, Arial', fontSize: '14px',
    clusterBkg: '#FAFAFB', clusterBorder: '#C9CDD4' },
  flowchart: { useMaxWidth: true, htmlLabels: true, curve: 'basis' },
  sequence: { useMaxWidth: true }, gantt: { useMaxWidth: true, barHeight: 22, fontSize: 12 } });
mermaid.run({ querySelector: '.mermaid' }).then(() => document.body.setAttribute('data-ready', '1'));
"""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Claro Copiloto · Documento de Arquitectura de Solución</title><style>{css}</style>
<script src="{mermaid_js.as_uri()}"></script></head>
<body>{cover}{toc}<main>{body}</main><script>{mermaid_cfg}</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mermaid", required=True, type=Path)
    ap.add_argument("--browser", default=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    a = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    html_path = OUT_DIR / "Claro_Copiloto_SAD.html"
    pdf_path = OUT_DIR / "Claro_Copiloto_SAD.pdf"
    md_all = build_markdown()
    (OUT_DIR / "Claro_Copiloto_SAD.md").write_text(md_all, encoding="utf-8")
    html_path.write_text(to_html(md_all, a.mermaid.resolve()), encoding="utf-8")
    profile = tempfile.mkdtemp(prefix="sad-browser-")   # perfil aislado: no choca con el navegador abierto
    subprocess.run([
        a.browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={profile}",
        "--allow-file-access-from-files", "--virtual-time-budget=40000",
        f"--print-to-pdf={pdf_path}", html_path.as_uri(),
    ], check=True, timeout=180)
    print("OK", pdf_path)


if __name__ == "__main__":
    main()
