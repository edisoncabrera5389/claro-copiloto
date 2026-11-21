// Genera la PPT de arquitectura "Claro Copiloto".
// Uso: node build_deck.js  (requiere pptxgenjs, react-icons, react, react-dom, sharp)
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
// Opcional: módulo que escribe la paleta en el tema del .pptx
const applyTheme = process.env.APPLY_THEME ? require(process.env.APPLY_THEME).applyTheme : null;

const OUT = path.join(__dirname, "Claro_Copiloto_Arquitectura.pptx");

const THEME = {
  name: "Claro Copiloto",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1A1D29", lt1: "FFFFFF", dk2: "3D4A5C", lt2: "F3F4F6",
    accent1: "DA291C", accent2: "2A6F97", accent3: "1F8A70",
    accent4: "E09F3E", accent5: "6A4C93", accent6: "8C939F",
    hlink: "2A6F97", folHlink: "6A4C93",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "Claro Copiloto – Propuesta de arquitectura";
pres.author = "Edison Cabrera";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const S = pres.shapes;

// ---------- iconos ----------
async function icon(name, hex, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(fa[name], { color: "#" + hex, size: String(size) })
  );
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// ---------- logo (SVG sin tamaño -> PNG liviano, rojo y blanco) ----------
const fs = require("fs");
const LOGO_SVG = path.join(__dirname, "assets", "logo-claro-rojo.svg");
const LOGO_RED = path.join(__dirname, "assets", "logo-claro-rojo.png");
const LOGO_WHITE = path.join(__dirname, "assets", "logo-claro-blanco.png");
const LOGO_RATIO = 69.9 / 193.5;
async function buildLogos() {
  fs.mkdirSync(path.dirname(LOGO_RED), { recursive: true });
  const svg = fs.readFileSync(LOGO_SVG, "utf8");
  await sharp(Buffer.from(svg), { density: 300 }).resize({ width: 600 }).png({ compressionLevel: 9 }).toFile(LOGO_RED);
  await sharp(Buffer.from(svg.replace(/#DA291C/gi, "#FFFFFF")), { density: 300 }).resize({ width: 600 }).png({ compressionLevel: 9 }).toFile(LOGO_WHITE);
}

// ---------- layouts ----------
pres.defineSlideMaster({
  title: "PORTADA",
  background: { color: HEX.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.5, h: 1.4, fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.75, w: 11.5, h: 1.0, fontSize: 22, color: C.background2, valign: "top", margin: 0 }, text: "" } },
    { image: { path: LOGO_WHITE, x: 0.8, y: 0.8, w: 2.6, h: 2.6 * LOGO_RATIO, altText: "Logo Claro" } },
  ],
});

pres.defineSlideMaster({
  title: "CONTENIDO",
  background: { color: HEX.lt1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.3, w: 12.1, h: 0.7, fontSize: 32, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 1.0, w: 12.1, h: 0.5, fontSize: 16, italic: true, color: C.text2, valign: "top", margin: 0 }, text: "" } },
    { text: { text: "Claro Copiloto · Propuesta de arquitectura · Edison Cabrera", options: { x: 0.6, y: 7.05, w: 8, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
    { image: { path: LOGO_RED, x: 11.2, y: 7.0, w: 0.9, h: 0.9 * LOGO_RATIO, altText: "Logo Claro" } },
  ],
  slideNumber: { x: 12.2, y: 7.05, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

// ---------- helpers ----------
const shadow = () => ({ type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.12 });

function content(section, title, lead) {
  const s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (lead) s.addText(lead, { placeholder: "body" });
  return s;
}

function box(s, x, y, w, h, text, o = {}) {
  s.addText(text, {
    shape: S.ROUNDED_RECTANGLE, rectRadius: 0.08, x, y, w, h,
    fill: { color: o.fill || C.background1 },
    line: { color: o.line || C.accent6, width: o.lw || 1, dashType: o.dash || "solid" },
    fontSize: o.fs || 12, bold: !!o.bold, color: o.color || C.text1,
    align: o.align || "center", valign: o.valign || "middle", margin: o.margin ?? 4,
    shadow: o.shadow ? shadow() : undefined, objectName: o.name,
  });
}

function group(s, x, y, w, h, label, colr) {
  s.addShape(S.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: C.background2 }, line: { color: C.background2, width: 0.5 } });
  s.addText(label, { x: x + 0.12, y: y + 0.05, w: w - 0.24, h: 0.3, fontSize: 11, bold: true, color: colr || C.text2, margin: 0, isTextBox: true });
}

// flecha recta; dir: r,l,d,u
function arrow(s, x, y, len, dir = "r", o = {}) {
  const horiz = dir === "r" || dir === "l";
  s.addShape(S.LINE, {
    x, y, w: horiz ? len : 0, h: horiz ? 0 : len,
    flipH: dir === "l", flipV: dir === "u",
    line: { color: o.color || C.text2, width: o.w || 1.5, endArrowType: "triangle", dashType: o.dash || "solid", beginArrowType: o.both ? "triangle" : undefined },
  });
}

function text(s, t, x, y, w, h, o = {}) {
  s.addText(t, { x, y, w, h, fontSize: o.fs || 14, color: o.color || C.text1, bold: !!o.bold, italic: !!o.italic, align: o.align || "left", valign: o.valign || "top", margin: o.margin ?? 0, isTextBox: true, paraSpaceAfter: o.psa, objectName: o.name });
}

function bullets(items, fs = 14, colr) {
  return items.map((it, i) => {
    const runs = typeof it === "string" ? { text: it } : it;
    return { text: runs.text, options: { bullet: true, fontSize: fs, color: colr || C.text1, bold: !!runs.bold, breakLine: i < items.length - 1, paraSpaceAfter: 4 } };
  });
}

function card(s, x, y, w, h, o = {}) {
  s.addShape(S.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: o.fill || C.background1 }, line: { color: o.line || "E2E4E8", width: 0.75 }, shadow: shadow(), objectName: o.name });
}

async function iconCircle(s, name, x, y, d, bg, fg = "FFFFFF") {
  s.addShape(S.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg, width: 0.5 } });
  const pad = d * 0.24;
  s.addImage({ data: await icon(name, fg), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad });
}

const tblHead = (cells, fill) => cells.map((c) => ({ text: c, options: { bold: true, color: "FFFFFF", fill: { color: fill || HEX.dk2 }, fontSize: 12 } }));

(async () => {
  await buildLogos();
  // =========================================================
  // 1. PORTADA
  // =========================================================
  pres.addSection({ title: "Inicio" });
  let s = pres.addSlide({ masterName: "PORTADA", sectionTitle: "Inicio" });
  s.addText("Claro Copiloto", { placeholder: "title" });
  s.addText("Asistente de IA generativa para atención y retención · Propuesta de arquitectura", { placeholder: "body" });
  text(s, "Prueba técnica · Líder Técnico AI Senior", 0.8, 5.4, 8, 0.4, { fs: 16, color: C.background1, bold: true });
  text(s, "Edison Cabrera · 21 de noviembre de 2026", 0.8, 5.8, 8, 0.4, { fs: 14, color: C.accent6 });
  text(s, "RAG · Agentes · MCP · Multi-LLM · MLOps · LLMOps · IaC · CI/CD", 0.8, 6.5, 11, 0.4, { fs: 14, color: C.accent6, italic: true });
  s.addNotes("Presentación: soy Edison Cabrera. Les voy a mostrar Claro Copiloto: un asistente de IA generativa para los asesores que combina RAG con citas, un agente con herramientas sobre CRM y facturación, modelos de ML clásico y una operación LLMOps completa. Todo lo que muestro aquí está respaldado por una demo funcional local, con la IaC lista para Azure. Estructura: problema, solución, arquitectura, operación y valor de negocio.");

  // =========================================================
  // 2. RESUMEN EJECUTIVO
  // =========================================================
  pres.addSection({ title: "Problema" });
  s = content("Problema", "El problema y los objetivos", "El asesor no debería buscar, debería decidir: respuesta citada, datos del cliente y acción confirmada");
  const probs = [
    ["FaClock", "AHT alto", "Búsqueda manual en catálogo, contratos, políticas, manuales y correos del NOC", "AHT −20 %"],
    ["FaRandom", "Inconsistencia", "Cada asesor interpreta el documento que encuentra; versiones viejas circulando", "Exactitud ≥ 80 %"],
    ["FaRedo", "FCR bajo", "Reglas complejas: ajustes > $50.000, LOS > 10 min, escalamientos", "FCR +10 pp"],
    ["FaUserMinus", "Retención perdida", "No se cruzan antigüedad, mora, ofertas previas y tickets a tiempo", "Retención medida"],
  ];
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + i * 3.08;
    card(s, x, 1.75, 2.85, 2.9);
    await iconCircle(s, probs[i][0], x + 0.25, 1.92, 0.6, HEX.accent1);
    text(s, probs[i][1], x + 0.25, 2.62, 2.4, 0.4, { fs: 18, bold: true });
    text(s, probs[i][2], x + 0.25, 3.05, 2.4, 0.95, { fs: 13, color: C.text2 });
    box(s, x + 0.25, 4.08, 2.35, 0.38, probs[i][3], { fill: C.background2, line: HEX.lt2, fs: 13, bold: true, color: C.accent1 });
  }
  text(s, "Metas del MVP", 0.6, 4.9, 6, 0.35, { fs: 14, bold: true, color: C.text2 });
  const stats = [["−20 %", "AHT"], ["+10 pp", "FCR"], ["≥ 0,85", "Groundedness de respuestas"], ["< US$0,02", "Costo por conversación"]];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.08;
    card(s, x, 5.3, 2.85, 1.5, { fill: i === 0 ? C.accent1 : C.background2, line: i === 0 ? HEX.accent1 : HEX.lt2 });
    text(s, st[0], x + 0.15, 5.42, 2.55, 0.75, { fs: 32, bold: true, align: "center", color: i === 0 ? C.background1 : C.accent1 });
    text(s, st[1], x + 0.15, 6.2, 2.55, 0.4, { fs: 13, align: "center", color: i === 0 ? C.background1 : C.text2 });
  });
  s.addNotes("Mensaje principal: el asesor no debería buscar, debería decidir. Cuatro problemas del caso, cada uno con su causa raíz y su KPI. El conocimiento cambia con frecuencia (catálogo v2, comunicados del NOC), por eso necesitamos ingesta automática y versionado. Validé todos los insumos: 14 documentos, 50 transcripciones y 3 audios, 3.816 tickets con 20 duplicados, 3.012 clientes con duplicados, atípicos como antigüedad negativa o 8.786 GB de consumo y nulos, PII en transcripciones, y 2 APIs que simulan 60 req/min y 2% de errores 503. Las metas del MVP: AHT -20%, FCR +10pp, groundedness 0,85 y costo por conversación medido por debajo de 2 centavos de dólar.");

  // =========================================================
  // 4. ACTORES Y CASOS DE USO
  // =========================================================
  s = content("Problema", "Actores y casos de uso del MVP", "9 casos de uso, cada uno con preguntas del golden dataset que lo prueban");
  const actors = [["FaHeadset", "Asesor N1", "usuario principal"], ["FaUserTie", "Supervisor", "escalamientos y aprobaciones"], ["FaTools", "Nivel 2 / Mesa retención", "tickets y alto valor"], ["FaFileAlt", "Dueños de contenido", "publican documentos"], ["FaChartLine", "Equipo IA / MLOps", "opera la calidad"]];
  card(s, 0.6, 1.75, 3.5, 5.05);
  text(s, "Actores", 0.85, 1.9, 3, 0.35, { fs: 16, bold: true });
  for (let i = 0; i < actors.length; i++) {
    const y = 2.4 + i * 0.86;
    await iconCircle(s, actors[i][0], 0.85, y, 0.55, i === 0 ? HEX.accent1 : HEX.dk2);
    text(s, actors[i][1], 1.55, y - 0.02, 2.45, 0.3, { fs: 14, bold: true });
    text(s, actors[i][2], 1.55, y + 0.28, 2.45, 0.3, { fs: 12, color: C.text2 });
  }
  const cus = [
    ["CU-01", "Pregunta con cita", "RAG híbrido", "GQ-01…24"],
    ["CU-02", "Ficha del cliente", "Tools CRM/Facturación", "GQ-25"],
    ["CU-03", "Oferta de retención", "Política + churn", "GQ-13…15, 26–28"],
    ["CU-04", "Acción con efecto", "Confirmación humana", "GQ-28"],
    ["CU-05", "Escalamiento", "Tema sensible / confianza", "GQ-29"],
    ["CU-06", "Fuera de alcance", "Guardrail de dominio", "GQ-30"],
    ["CU-07", "Resumen e intención", "LLM + ML, sin PII", "Transcripciones"],
    ["CU-08", "Nueva versión de doc", "Ingesta automática", "Catálogo v2"],
    ["CU-09", "Audio a texto", "Whisper + PII", "3 audios"],
  ];
  cus.forEach((cu, i) => {
    const x = 4.4 + (i % 3) * 2.8, y = 1.75 + Math.floor(i / 3) * 1.72;
    card(s, x, y, 2.6, 1.55, { fill: C.background2, line: HEX.lt2 });
    text(s, cu[0], x + 0.15, y + 0.1, 1.2, 0.3, { fs: 12, bold: true, color: C.accent1 });
    text(s, cu[1], x + 0.15, y + 0.4, 2.3, 0.35, { fs: 15, bold: true });
    text(s, cu[2], x + 0.15, y + 0.78, 2.3, 0.3, { fs: 12, color: C.text2 });
    text(s, cu[3], x + 0.15, y + 1.1, 2.3, 0.3, { fs: 11, italic: true, color: C.accent2 });
  });
  s.addNotes("Actores: el asesor es el usuario principal; el supervisor aprueba ajustes mayores a 50.000 y recibe escalamientos; nivel 2 y la mesa de retención reciben tickets y clientes de alto valor. El MVP cubre 9 casos de uso. Cada uno está amarrado a preguntas del golden dataset, así la evaluación automática prueba exactamente lo que prometemos. Alcance fuera del MVP: canal de cliente final, voz en tiempo real, integración real con CRM y datos de red en streaming, que quedan diseñados en el roadmap.");

  // =========================================================
  // 5. POR QUÉ IA GENERATIVA
  // =========================================================
  s = content("Problema", "¿Por qué IA generativa y no otra solución?", "Combinar RAG + agente + ML clásico: cada técnica donde rinde más");
  const rows = [
    ["Buscador documental", "Devuelve documentos, no respuestas: el asesor sigue leyendo", "No baja AHT"],
    ["Chatbot de reglas", "Frágil al lenguaje natural; mantenimiento alto con documentos cambiantes", "No escala"],
    ["Solo ML clásico", "Clasifica y predice, pero no redacta ni razona sobre políticas", "Complemento"],
    ["Fine-tuning como conocimiento", "Reentrenar por cada catálogo; sin citas ni trazabilidad", "Solo para estilo"],
  ];
  const tb = [tblHead(["Alternativa", "Limitación", "Veredicto"])];
  rows.forEach((r) => tb.push([{ text: r[0], options: { bold: true } }, r[1], { text: r[2], options: { color: HEX.accent1, bold: true } }]));
  s.addTable(tb, { x: 0.6, y: 1.8, w: 7.4, colW: [2.1, 3.9, 1.4], fontSize: 13, color: HEX.dk1, border: { type: "solid", pt: 0.5, color: "E2E4E8" }, rowH: [0.6, 1.05, 1.05, 1.05, 1.05], valign: "middle", fontFace: "Calibri" });
  card(s, 8.4, 1.8, 4.3, 4.8, { fill: C.text1, line: HEX.dk1 });
  await iconCircle(s, "FaCheckCircle", 8.7, 2.05, 0.65, HEX.accent1);
  text(s, "Decisión", 9.5, 2.15, 3, 0.45, { fs: 20, bold: true, color: C.background1 });
  s.addText(bullets([
    { text: "LLM: entiende, sintetiza varias fuentes y cita", bold: false },
    "Reglas críticas (elegibilidad, límites de ajuste) en código determinístico dentro de las tools",
    "ML clásico: intención y churn rápidos, baratos y explicables",
    "Fine-tuning: experimento para estilo y clasificador económico",
  ], 14, C.background1), { x: 8.7, y: 2.9, w: 3.8, h: 3.7, valign: "top", margin: 0, isTextBox: true });
  s.addNotes("Justificación de IA generativa. Un buscador no baja el AHT porque devuelve documentos. Un bot de reglas no aguanta lenguaje natural ni el cambio de contenido. El ML clásico es excelente para clasificar y predecir, por eso lo uso, pero no redacta respuestas. Sobre fine-tuning, que el caso menciona: no lo uso como fuente de conocimiento porque el contenido cambia y perdería las citas; sí lo planteo como experimento para estilo corporativo y para un clasificador barato. Principio de diseño clave: el LLM razona y redacta, pero las reglas de negocio se ejecutan en código.");

  // =========================================================
  // 6. ARQUITECTURA DE COMPONENTES
  // =========================================================
  pres.addSection({ title: "Arquitectura" });
  s = content("Arquitectura", "Arquitectura de referencia", "Cinco capas desacopladas; la misma imagen corre en Docker Compose y en Azure Container Apps");
  group(s, 0.6, 1.65, 2.3, 2.95, "EXPERIENCIA", C.accent1);
  box(s, 0.75, 2.05, 2.0, 0.9, "Angular SPA\nchat streaming · citas", { line: HEX.accent1, lw: 1.5, bold: true });
  box(s, 0.75, 3.1, 2.0, 1.3, "Ficha cliente\n👍👎 · Escalar\nConfirmar acción", { line: HEX.accent1, fs: 11 });

  group(s, 3.2, 1.65, 5.7, 2.95, "APLICACIÓN · PYTHON", C.accent2);
  box(s, 3.35, 2.0, 5.4, 0.5, "API Gateway · FastAPI — JWT por rol · rate limit · SSE · OpenAPI", { line: HEX.accent2, lw: 1.5, bold: true });
  box(s, 3.35, 2.65, 3.9, 0.6, "Orquestador agéntico · LangGraph", { line: HEX.accent2, lw: 1.5, bold: true, fill: C.background1 });
  box(s, 7.35, 2.65, 1.4, 0.6, "Guardrails\nPII · injection", { line: HEX.accent1, fs: 11 });
  box(s, 3.35, 3.5, 1.7, 0.95, "MCP Server\ntools + skills", { line: HEX.accent2, bold: true });
  box(s, 5.2, 3.5, 1.7, 0.95, "LLM Gateway\nLiteLLM", { line: HEX.accent2, bold: true });
  box(s, 7.05, 3.5, 1.7, 0.95, "ML Service\nintención · churn", { line: HEX.accent2, bold: true });

  group(s, 9.2, 1.65, 3.5, 2.95, "SISTEMAS EXTERNOS", C.text2);
  box(s, 9.35, 2.0, 1.55, 0.6, "CRM API", { line: HEX.dk2 });
  box(s, 11.0, 2.0, 1.55, 0.6, "Facturación API", { line: HEX.dk2 });
  box(s, 9.35, 2.75, 1.55, 0.6, "OpenAI", { line: HEX.dk2 });
  box(s, 11.0, 2.75, 1.55, 0.6, "Ollama\nLlama · Mistral", { line: HEX.dk2, fs: 11 });
  box(s, 9.35, 3.5, 1.55, 0.95, "n8n · RPA\ntickets · avisos", { line: HEX.dk2, fs: 11 });
  box(s, 11.0, 3.5, 1.55, 0.95, "ERP (mock)\najustes · órdenes", { line: HEX.dk2, fs: 11 });
  arrow(s, 10.9, 3.975, 0.1, "r");

  group(s, 0.6, 4.85, 2.3, 1.95, "INGESTA Y STREAMING", C.accent4);
  box(s, 0.75, 5.2, 2.0, 0.42, "Watcher · Blob/Event", { line: HEX.accent4, fs: 10 });
  box(s, 0.75, 5.72, 2.0, 0.5, "Worker: OCR · Whisper\nPII · chunking", { line: HEX.accent4, fs: 10 });
  box(s, 0.75, 6.32, 2.0, 0.4, "Red NRT: Kafka → Redis", { line: HEX.accent4, fs: 10, dash: "dash" });
  arrow(s, 1.75, 5.62, 0.1, "d", { color: C.accent4 });

  group(s, 3.2, 4.85, 5.7, 1.95, "DATOS Y MEMORIA", C.accent3);
  const dbs = [["Qdrant", "vector + BM25"], ["Redis", "memoria corta · caché"], ["MongoDB", "memoria larga · auditoría"], ["MLflow", "registry de modelos"]];
  dbs.forEach((d, i) => box(s, 3.35 + i * 1.375, 5.25, 1.275, 1.4, d[0] + "\n" + d[1], { line: HEX.accent3, fs: 11 }));

  group(s, 9.2, 4.85, 3.5, 1.95, "OBSERVABILIDAD · LLMOPS", C.accent5);
  box(s, 9.35, 5.25, 1.0, 1.4, "Phoenix\nOTel", { line: HEX.accent5, fs: 11 });
  box(s, 10.45, 5.25, 1.0, 1.4, "Prome-\ntheus", { line: HEX.accent5, fs: 11 });
  box(s, 11.55, 5.25, 1.0, 1.4, "Grafana\ntableros", { line: HEX.accent5, fs: 11 });

  arrow(s, 2.75, 2.25, 0.6, "r");
  arrow(s, 6.05, 2.5, 0.15, "d");
  arrow(s, 5.05, 3.25, 0.25, "d");
  arrow(s, 8.75, 3.95, 0.6, "r");
  arrow(s, 6.05, 4.45, 0.8, "d", { both: true });
  arrow(s, 2.75, 5.97, 0.6, "r", { color: C.accent4 });
  arrow(s, 8.9, 5.95, 0.3, "r", { color: C.accent5, dash: "dash" });
  s.addNotes("Arquitectura en cinco capas. Experiencia: Angular con streaming por SSE, citas y confirmación de acciones. Aplicación en Python: FastAPI como gateway con JWT y roles; el orquestador LangGraph con guardrails a la entrada y salida; el MCP server es el único punto de acceso a CRM y facturación; LiteLLM rutea entre OpenAI y modelos open source locales; el servicio de ML sirve intención y churn. Datos: Qdrant para búsqueda híbrida, Redis para memoria corta y caché semántico, MongoDB para memoria larga y auditoría, MLflow para modelos. Ingesta por eventos; la telemetría de red near real time entra por Kafka/Event Hubs, se agrega por zona en Redis y el agente la consulta con la tool consultarEstadoRed, así detecta incidentes masivos sin esperar el correo del NOC. n8n orquesta la automatización cognitiva hacia tickets, notificaciones y el ERP. Observabilidad con OpenTelemetry, Phoenix, Prometheus y Grafana. Todo es contenedor: la misma imagen corre local y en Azure.");

  // =========================================================
  // 7. FLUJO AGÉNTICO
  // =========================================================
  s = content("Arquitectura", "Flujo agéntico con límites de autonomía", "El agente propone, el asesor dispone: las acciones con efecto requieren confirmación");
  const nY = 3.05, nH = 0.85, nW = 1.4;
  const nodes = [
    [0.6, "Mensaje\nasesor", HEX.dk2],
    [2.2, "Guardrail\nentrada", HEX.accent1],
    [3.8, "Clasificar\nintención", HEX.accent2],
    [5.4, "Planner", HEX.accent2],
  ];
  nodes.forEach((n) => box(s, n[0], nY, nW, nH, n[1], { line: n[2], lw: 1.75, bold: true, fs: 13 }));
  [[2.0], [3.6], [5.2]].forEach((a) => arrow(s, a[0], nY + nH / 2, 0.2, "r"));
  const par = [["RAG híbrido\n+ rerank + vigencia", 1.95], ["Tools MCP\nCRM · Facturación", 3.05], ["Skill retención\nreglas + churn", 4.15]];
  par.forEach((p) => box(s, 7.15, p[1], 1.75, 0.85, p[0], { line: HEX.accent3, lw: 1.5, fs: 12 }));
  s.addShape(S.LINE, { x: 6.8, y: 2.375, w: 0, h: 2.2, line: { color: HEX.dk2, width: 1.5 } });
  arrow(s, 6.8, nY + nH / 2, 0.35, "r");
  arrow(s, 6.8, 2.375, 0.35, "r");
  arrow(s, 6.8, 4.575, 0.35, "r");
  s.addShape(S.LINE, { x: 9.1, y: 2.375, w: 0, h: 2.2, line: { color: HEX.dk2, width: 1.5 } });
  [2.375, 3.475, 4.575].forEach((y) => s.addShape(S.LINE, { x: 8.9, y, w: 0.2, h: 0, line: { color: HEX.dk2, width: 1.5 } }));
  arrow(s, 9.1, nY + nH / 2, 0.2, "r");
  box(s, 9.3, nY, 1.45, nH, "Generar\ncon citas", { line: HEX.accent2, lw: 1.75, bold: true, fs: 13 });
  arrow(s, 10.75, nY + nH / 2, 0.2, "r");
  box(s, 10.95, nY, 1.75, nH, "Guardrail salida\ncitas · PII · confianza", { line: HEX.accent1, lw: 1.75, bold: true, fs: 12 });
  box(s, 2.2, 1.75, nW, 0.7, "Fuera de alcance\n→ rechazo amable", { line: HEX.accent6, fs: 11, dash: "dash" });
  arrow(s, 2.9, 2.45, 0.6, "u", { color: C.accent6 });
  box(s, 0.6, 4.55, 3.0, 0.75, "Escalar a supervisor\nSIC · tutela · fraude · baja confianza", { line: HEX.accent1, fs: 12, fill: C.background2 });
  arrow(s, 2.9, 3.9, 0.65, "d", { color: C.accent1 });
  box(s, 10.95, 4.45, 1.75, 0.85, "⏸ Confirmación\nasesor → POST", { line: HEX.accent4, lw: 1.75, fs: 12, bold: true });
  arrow(s, 11.825, 3.9, 0.55, "d", { color: C.accent4 });
  const lims = [["FaStopCircle", "Máx. 6 pasos / turno", "3 llamadas por tool → corta bucle y escala"], ["FaLock", "Escritura con HITL", "crearTicket · registrarOferta · aplicarAjuste"], ["FaBalanceScale", "Reglas en el tool", "mora > 30 d · 1 oferta/12 m · ajuste > $50.000"], ["FaTachometerAlt", "Confianza medida", "rerank + cobertura de citas + acuerdo ML/LLM"]];
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + i * 3.08;
    card(s, x, 5.6, 2.9, 1.2, { fill: C.background2, line: HEX.lt2 });
    await iconCircle(s, lims[i][0], x + 0.15, 5.78, 0.5, HEX.dk2);
    text(s, lims[i][1], x + 0.78, 5.72, 2.05, 0.35, { fs: 14, bold: true });
    text(s, lims[i][2], x + 0.78, 6.07, 2.05, 0.7, { fs: 11, color: C.text2 });
  }
  s.addNotes("El agente es un grafo explícito en LangGraph, no una cadena libre. Primero un guardrail de entrada detecta PII, prompt injection, temas fuera de alcance y temas sensibles que por política se escalan de inmediato, como menciones de SIC o tutela. Luego clasifica intención: primero con el modelo de ML, que cuesta casi cero, y solo si la confianza es baja con un LLM. El planner decide qué ramas ejecutar: RAG, tools de CRM y facturación, o la skill de retención que aplica la matriz de la política en código. Se genera con citas y un guardrail de salida valida que cada afirmación tenga cita y que no haya PII. Las acciones con efecto se pausan para confirmación del asesor. Límites: 6 pasos por turno y detección de bucles.");

  // =========================================================
  // 8. INGESTA + RAG
  // =========================================================
  s = content("Arquitectura", "Fuentes automatizadas y RAG con control de alucinaciones", "Un documento nuevo queda disponible y citado sin intervención manual");
  const steps = [["FaFolderOpen", "Carpeta / Blob", "evento"], ["FaFingerprint", "Hash SHA-256", "idempotente"], ["FaFileAlt", "Extracción", "PDF · tablas · DOCX · EML"], ["FaMicrophone", "OCR · Whisper", "imágenes y audio"], ["FaUserSecret", "PII Presidio", "cédula · celular · email"], ["FaCut", "Chunking", "por sección / tabla"], ["FaDatabase", "Qdrant + Mongo", "vector · BM25 · versión"]];
  for (let i = 0; i < steps.length; i++) {
    const x = 0.6 + i * 1.75;
    card(s, x, 1.7, 1.55, 1.75);
    await iconCircle(s, steps[i][0], x + 0.5, 1.85, 0.55, i === 4 ? HEX.accent1 : HEX.accent4);
    text(s, steps[i][1], x + 0.08, 2.5, 1.4, 0.35, { fs: 13, bold: true, align: "center" });
    text(s, steps[i][2], x + 0.08, 2.85, 1.4, 0.55, { fs: 11, color: C.text2, align: "center" });
    if (i < steps.length - 1) arrow(s, x + 1.55, 2.575, 0.2, "r");
  }
  card(s, 0.6, 3.75, 6.9, 3.05, { fill: C.background2, line: HEX.lt2 });
  text(s, "RAG en consulta", 0.85, 3.9, 5, 0.4, { fs: 16, bold: true });
  s.addText(bullets([
    "Búsqueda híbrida semántica + BM25 con fusión RRF: no pierde códigos como E-202, LOS o RET-A",
    "Reranking cross-encoder local (top-20 → top-5) y filtro obligatorio vigente = true",
    "Cita [n] por afirmación; linaje chunk → documento → versión → hash en MongoDB",
    "Validador de citas + umbral de confianza → «no encontrado, escalo»",
  ], 14), { x: 0.85, y: 4.35, w: 6.45, h: 2.4, valign: "top", margin: 0, isTextBox: true });
  card(s, 7.8, 3.75, 4.9, 3.05, { fill: C.text1, line: HEX.dk1 });
  text(s, "Demo: catálogo v2", 8.1, 3.9, 4.3, 0.4, { fs: 16, bold: true, color: C.background1 });
  s.addText(bullets(["Se copia el PDF v2 a la carpeta vigilada", "El pipeline lo detecta y lo indexa", "La v1 pasa a vigente = false", "El copiloto cita la versión 2.0"], 14, C.background1), { x: 8.1, y: 4.35, w: 2.9, h: 2.3, valign: "top", margin: 0, isTextBox: true });
  text(s, "≤ 15", 10.95, 4.5, 1.6, 0.9, { fs: 44, bold: true, color: C.accent1, align: "center" });
  text(s, "min de frescura medida", 10.95, 5.4, 1.6, 0.7, { fs: 12, color: C.background1, align: "center" });
  s.addNotes("La automatización de fuentes es event-driven: local con una carpeta vigilada y Redis Streams, en Azure con Blob Storage, Event Grid y un Container Apps Job. El hash hace el pipeline idempotente. Extraigo PDF con tablas, Word, correos y Markdown; OCR si no hay capa de texto y Whisper para los audios. Antes de indexar anonimizo PII con Presidio más reglas colombianas. El chunking respeta secciones y deja las tablas completas, que es donde están tarifas y la matriz de retención. Cada chunk lleva documento, versión, vigencia, página y fecha. En consulta: búsqueda híbrida porque en telco hay muchos códigos que la búsqueda vectorial pura pierde, reranking y filtro de vigencia. En la demo voy a copiar el catálogo v2 y medir la frescura.");

  // =========================================================
  // 9. MULTI-LLM + MEMORIA + MCP
  // =========================================================
  s = content("Arquitectura", "Multi-LLM, memoria y MCP", "El modelo más barato que resuelve la tarea, con fallback y sin acoplar proveedores");
  const rt = [tblHead(["Tarea", "Primario", "Fallback"])];
  [["Intención", "ML clásico (≈ 1 ms)", "LLM económico"], ["Respuesta RAG", "OpenAI tier económico", "Llama / Mistral local"], ["Multi-tool / retención", "OpenAI tier alto", "Tier económico"], ["Resumen de cierre", "Tier económico", "Modelo local"], ["LLM-as-judge", "Tier alto", "—"]].forEach((r) => rt.push([{ text: r[0], options: { bold: true } }, r[1], r[2]]));
  s.addTable(rt, { x: 0.6, y: 1.75, w: 6.6, colW: [2.0, 2.4, 2.2], fontSize: 13, color: HEX.dk1, border: { type: "solid", pt: 0.5, color: "E2E4E8" }, rowH: 0.5, valign: "middle", fontFace: "Calibri" });
  s.addText(bullets(["LiteLLM: ruteo por tarea, costo y presupuesto; fallback ante timeout, 429 o 5xx", "Claude, Gemini o Azure OpenAI se agregan por configuración, sin tocar código", "Caché semántico en Redis para preguntas repetidas de política"], 14), { x: 0.6, y: 4.95, w: 6.6, h: 1.85, valign: "top", margin: 0, isTextBox: true });
  card(s, 7.5, 1.75, 2.5, 2.6);
  await iconCircle(s, "FaBolt", 7.7, 1.9, 0.55, HEX.accent1);
  text(s, "Redis · corto plazo", 7.7, 2.55, 2.2, 0.35, { fs: 14, bold: true });
  text(s, "Sesión y checkpoint del grafo (TTL 2 h), ficha cacheada, caché semántico, rate limit", 7.7, 2.9, 2.2, 1.4, { fs: 12, color: C.text2 });
  card(s, 10.2, 1.75, 2.5, 2.6);
  await iconCircle(s, "FaLeaf", 10.4, 1.9, 0.55, HEX.accent3);
  text(s, "MongoDB · largo plazo", 10.4, 2.55, 2.2, 0.35, { fs: 14, bold: true });
  text(s, "Resúmenes por cliente sin PII, historial, feedback y auditoría de decisiones", 10.4, 2.9, 2.2, 1.4, { fs: 12, color: C.text2 });
  card(s, 7.5, 4.6, 5.2, 2.2, { fill: C.background2, line: HEX.lt2 });
  await iconCircle(s, "FaPlug", 7.7, 4.75, 0.55, HEX.accent2);
  text(s, "MCP Server · contrato tipado", 8.4, 4.85, 4.1, 0.35, { fs: 14, bold: true });
  const tools = ["obtenerCliente", "listarTickets", "listarFacturas", "obtenerSaldo", "evaluarRetencion", "crearTicket", "registrarOferta", "aplicarAjuste"];
  text(s, "Naranja = escritura: requiere confirmación del asesor", 7.7, 6.6, 4.9, 0.25, { fs: 10, italic: true, color: C.accent4 });
  tools.forEach((t, i) => box(s, 7.7 + (i % 4) * 1.25, 5.45 + Math.floor(i / 4) * 0.6, 1.15, 0.45, t, { fs: 10, line: i >= 5 ? HEX.accent4 : HEX.accent2, fill: C.background1 }));
  s.addNotes("Multi-LLM: no todo merece el modelo más caro. La intención la resuelve el ML clásico en un milisegundo. La respuesta RAG estándar va al tier económico de OpenAI; el tier alto solo cuando hay varias tools o cálculos, como retención. LiteLLM hace el ruteo y el fallback a un modelo open source local con Ollama si OpenAI falla o da rate limit. Agregar Claude o Gemini es configuración. Memoria: Redis para lo efímero y de baja latencia, MongoDB para memoria larga y auditoría, porque son patrones de acceso distintos. MCP: las tools viven en un servidor MCP con contrato tipado, reutilizable por otros agentes o canales; las de escritura, con candado, exigen confirmación.");

  // =========================================================
  // 10. ML + LLMOPS
  // =========================================================
  pres.addSection({ title: "Operación" });
  s = content("Operación", "ML clásico y LLMOps: calidad medida en cada cambio", "Ningún prompt, modelo o documento llega a producción sin pasar el golden dataset");
  const mls = [["FaTags", "Clasificador de intención", "164 descripciones únicas → validación agrupada", "TF-IDF n-gramas de caracteres + SVM lineal calibrado", "F1 macro 0,92"], ["FaUserClock", "Riesgo de churn 90 días", "Regresión logística vs RF, LightGBM y CatBoost", "Interpretable: explica el riesgo al asesor", "AUC 0,70 · meta 0,75"]];
  for (let i = 0; i < 2; i++) {
    const y = 1.75 + i * 2.15;
    card(s, 0.6, y, 5.6, 1.95);
    await iconCircle(s, mls[i][0], 0.85, y + 0.25, 0.6, HEX.accent2);
    text(s, mls[i][1], 1.65, y + 0.2, 4.4, 0.35, { fs: 16, bold: true });
    text(s, mls[i][2], 1.65, y + 0.6, 4.4, 0.3, { fs: 12, color: C.text2 });
    text(s, mls[i][3], 1.65, y + 0.92, 4.4, 0.3, { fs: 12, color: C.text2 });
    box(s, 1.65, y + 1.35, 2.4, 0.4, mls[i][4], { fs: 13, bold: true, color: C.accent1, fill: C.background2, line: HEX.lt2 });
  }
  text(s, "Fine-tuning OpenAI vs SVM vs prompt: comparativa en la demo · MLflow registry · API · drift PSI (Evidently) → alerta → reentrenamiento", 0.6, 6.15, 5.6, 0.65, { fs: 12, italic: true, color: C.text2 });
  const loop = [[8.65, 1.75, "Prompt y modelo\nversionados"], [10.85, 2.95, "Gate golden\nen CI"], [10.05, 5.0, "Despliegue\ncanary"], [7.25, 5.0, "Trazas Phoenix\ntokens · costo · latencia"], [6.45, 2.95, "Feedback 👍👎\n→ nuevos casos"]];
  loop.forEach((l, i) => box(s, l[0], l[1], 1.85, 0.95, l[2], { line: i === 1 ? HEX.accent1 : HEX.accent5, lw: 1.75, fs: 12, bold: true, shadow: true }));
  s.addShape(S.LINE, { x: 10.5, y: 2.22, w: 0.9, h: 0.73, line: { color: HEX.dk2, width: 1.5, endArrowType: "triangle" } });
  s.addShape(S.LINE, { x: 11.3, y: 3.9, w: 0.5, h: 1.1, flipH: true, line: { color: HEX.dk2, width: 1.5, endArrowType: "triangle" } });
  arrow(s, 9.1, 5.475, 0.95, "l");
  s.addShape(S.LINE, { x: 7.35, y: 3.9, w: 0.55, h: 1.1, flipH: true, flipV: true, line: { color: HEX.dk2, width: 1.5, endArrowType: "triangle" } });
  s.addShape(S.LINE, { x: 7.5, y: 2.22, w: 1.15, h: 0.73, flipV: true, line: { color: HEX.dk2, width: 1.5, endArrowType: "triangle" } });
  text(s, "Exactitud · groundedness · recall@k · éxito de tools", 8.25, 3.6, 2.6, 0.9, { fs: 12, italic: true, color: C.accent5, align: "center", valign: "middle" });
  s.addNotes("Dos modelos de ML clásico, elegidos comparando algoritmos con validación honesta. Hallazgo clave: hay solo 164 descripciones únicas en 3.816 tickets; un split aleatorio daba F1 0,97 por fuga de datos. Validando agrupado por descripción, Naive Bayes da 0,81, regresión logística 0,83 y SVM lineal con n-gramas de caracteres 0,92, que es el elegido y se calibra para tener confianza. Además hay ruido de etiquetas: la misma descripción en categorías distintas. Churn: regresión logística 0,70 de AUC, empatada con CatBoost y por encima de Random Forest y LightGBM; reporto con transparencia que está bajo la meta de 0,75 y lo uso como señal de priorización, nunca como decisión automática. El fine-tuning se compara contra el SVM en costo, latencia y F1. Ambos se registran en MLflow, se sirven por API y se monitorea drift con PSI. LLMOps: prompts y modelos versionados; el golden dataset de 30 preguntas corre en CI como gate con exactitud por puntos clave, groundedness con LLM como juez, recall@k y éxito de tools. Si una métrica cae, no se despliega. En producción, trazas con tokens, costo y latencia, y el feedback negativo alimenta nuevos casos de evaluación.");

  // =========================================================
  // 11. SEGURIDAD
  // =========================================================
  s = content("Operación", "Seguridad, privacidad e IA responsable", "Ley 1581: la PII no llega al LLM, no queda en logs y cada decisión es auditable");
  const sec = [
    ["FaUserSecret", "PII y Habeas Data", "Presidio en ingesta y salida de tools; documento, celular y email nunca salen del MCP server; masking en logs"],
    ["FaShieldAlt", "Prompt injection", "Contexto delimitado, detector de patrones, tools en allow-list y nada se ejecuta sin confirmación"],
    ["FaKey", "Acceso por rol", "JWT asesor / supervisor / admin; ajustes > $50.000 solo con supervisor; secretos en Key Vault"],
    ["FaBan", "Fuera de alcance y sesgos", "Guardrail de dominio, sin datos financieros ni de terceros; respuestas neutrales y citadas"],
    ["FaUserFriends", "Human-in-the-loop", "Escalamiento obligatorio por SIC, tutela, fraude o vulnerabilidad y por baja confianza"],
    ["FaClipboardCheck", "Auditoría", "Cada respuesta guarda fuentes y versión, modelo, prompt, costo y acción confirmada (MongoDB)"],
  ];
  for (let i = 0; i < 6; i++) {
    const x = 0.6 + (i % 3) * 4.08, y = 1.75 + Math.floor(i / 3) * 2.6;
    card(s, x, y, 3.85, 2.35);
    await iconCircle(s, sec[i][0], x + 0.25, y + 0.25, 0.65, i === 0 ? HEX.accent1 : HEX.dk2);
    text(s, sec[i][1], x + 1.1, y + 0.37, 2.6, 0.45, { fs: 16, bold: true });
    text(s, sec[i][2], x + 0.25, y + 1.05, 3.4, 1.25, { fs: 13, color: C.text2 });
  }
  s.addNotes("Seguridad por capas. PII: se anonimiza en la ingesta y se filtra en el MCP server, así el número de documento, el celular y el correo nunca llegan al modelo ni a las trazas; hay una prueba automática que busca PII en las respuestas. Prompt injection: separación estricta entre instrucciones y datos, detector y, sobre todo, ninguna acción con efecto sin confirmación humana, lo que limita el daño posible. Roles con JWT y aprobación de supervisor para ajustes grandes, igual que la política. Escalamiento obligatorio en los casos de la política de escalamiento. Y auditoría completa de cada decisión para cumplimiento.");

  // =========================================================
  // 12. DESPLIEGUE, IAC, CI/CD
  // =========================================================
  s = content("Operación", "Despliegue, IaC y CI/CD", "Un comando local, la misma arquitectura en Azure vía Terraform y entrega sin caída");
  const ci = ["Lint", "Tests", "Build imagen", "Trivy · Bandit", "Gate LLM + ML", "Terraform plan", "Deploy SHA", "Smoke tests"];
  ci.forEach((c, i) => {
    s.addText(c, { shape: S.CHEVRON, x: 0.6 + i * 1.5, y: 1.75, w: 1.55, h: 0.75, fill: { color: i === 4 ? C.accent1 : C.text2 }, line: { color: HEX.lt1, width: 1 }, fontSize: 12, bold: true, color: C.background1, align: "center", valign: "middle", margin: 2 });
  });
  text(s, "GitHub Actions · cobertura ≥ 70 % · self-hosted runner en la demo · rollback = volver a la revisión anterior (canary / blue-green en Container Apps)", 0.6, 2.6, 12.1, 0.35, { fs: 12, italic: true, color: C.text2 });
  const map = [tblHead(["Componente", "Local · docker compose up", "Azure · Terraform (dev / prod)"])];
  [["Cómputo", "Contenedores con healthcheck", "Container Apps + KEDA autoscaling"], ["Fuentes", "Carpeta vigilada + Redis Streams", "Blob Storage + Event Grid + ACA Job"], ["LLM", "OpenAI + Ollama (perfil opcional)", "Azure OpenAI / OpenAI"], ["Memoria", "Redis y MongoDB en contenedor", "Azure Cache for Redis · Cosmos DB (Mongo)"], ["Secretos", ".env local", "Key Vault + Managed Identity"], ["Observabilidad", "Phoenix · Prometheus · Grafana", "App Insights · Managed Grafana"]].forEach((r) => map.push([{ text: r[0], options: { bold: true } }, r[1], r[2]]));
  s.addTable(map, { x: 0.6, y: 3.1, w: 8.6, colW: [1.8, 3.2, 3.6], fontSize: 12, color: HEX.dk1, border: { type: "solid", pt: 0.5, color: "E2E4E8" }, rowH: 0.48, valign: "middle", fontFace: "Calibri" });
  card(s, 9.5, 3.1, 3.2, 3.7, { fill: C.background2, line: HEX.lt2 });
  await iconCircle(s, "FaDocker", 9.75, 3.3, 0.6, HEX.accent2);
  text(s, "Contenedores", 10.5, 3.42, 2.1, 0.4, { fs: 15, bold: true });
  s.addText(bullets(["Multi-stage, slim, usuario no root", "Healthchecks y límites de recursos", "Registro ACR con tag por SHA", "0 CVEs críticas como gate", "Ambientes por tfvars"], 13), { x: 9.75, y: 4.1, w: 2.8, h: 2.6, valign: "top", margin: 0, isTextBox: true });
  s.addNotes("CI/CD en GitHub Actions: lint, pruebas unitarias, de integración contra los mocks y end-to-end, build de imágenes multi-stage, escaneo con Trivy y Bandit, y el gate de calidad del LLM y del ML. Luego terraform validate y plan, deploy con tag por SHA y smoke tests. Sin nube disponible, la demo es local con un runner self-hosted: un commit llega al ambiente en minutos. La tabla muestra la equivalencia exacta entre local y Azure; Terraform tiene módulos y ambientes dev y prod por tfvars, con secretos en Key Vault. Elegí Container Apps sobre AKS por menor operación y KEDA incluido; rollback y canary con revisiones.");

  // =========================================================
  // 13. KPIs
  // =========================================================
  s = content("Operación", "Escalabilidad y resiliencia", "Servicios sin estado, fallback escalonado y degradación controlada: el asesor nunca queda sin respuesta");
  const scen = [
    ["FaUsers", "10.000 asesores concurrentes", "API y agente sin estado (estado en Redis), KEDA por RPS, réplicas de Qdrant, cuotas LLM multi-región, caché semántico y streaming"],
    ["FaPowerOff", "Falla del proveedor LLM", "Timeout y reintento con backoff, circuit breaker y fallback a otro modelo o proveedor sin cambiar código"],
    ["FaTachometerAlt", "Rate limits y errores de APIs", "CRM y Facturación: Retry-After ante 429, backoff ante 503, caché de ficha por sesión e idempotencia en POST"],
    ["FaExclamationCircle", "Calidad degradada tras un cambio", "Gate golden en CI y evaluación online por muestreo; alerta por 👎 o groundedness → rollback de prompt_version"],
  ];
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + (i % 2) * 3.55, y = 1.75 + Math.floor(i / 2) * 2.6;
    card(s, x, y, 3.35, 2.4);
    await iconCircle(s, scen[i][0], x + 0.2, y + 0.2, 0.55, i === 1 ? HEX.accent1 : HEX.dk2);
    text(s, scen[i][1], x + 0.9, y + 0.2, 2.3, 0.65, { fs: 15, bold: true, valign: "middle" });
    text(s, scen[i][2], x + 0.2, y + 0.95, 2.95, 1.4, { fs: 12, color: C.text2 });
  }
  card(s, 7.9, 1.75, 4.8, 5.05, { fill: C.background2, line: HEX.lt2 });
  text(s, "Degradación controlada", 8.15, 1.9, 4.3, 0.4, { fs: 16, bold: true });
  const lv = [["Normal", "Tier económico o alto según la tarea", HEX.accent3], ["Fallback de modelo", "Otro modelo u otro proveedor vía LiteLLM", HEX.accent2], ["Modelo local", "Llama / Mistral en Ollama", HEX.accent4], ["Modo búsqueda", "Fragmentos citados, sin generación", HEX.accent5], ["Escalar a humano", "Supervisor con contexto y resumen", HEX.accent1]];
  s.addShape(S.LINE, { x: 8.45, y: 2.7, w: 0, h: 3.6, line: { color: HEX.accent6, width: 1.5 } });
  lv.forEach((l, i) => {
    const y = 2.45 + i * 0.86;
    s.addText(String(i + 1), { shape: S.OVAL, x: 8.2, y, w: 0.5, h: 0.5, fill: { color: l[2] }, line: { color: HEX.lt1, width: 1.5 }, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0 });
    text(s, l[0], 8.9, y - 0.02, 3.6, 0.3, { fs: 14, bold: true });
    text(s, l[1], 8.9, y + 0.27, 3.6, 0.3, { fs: 12, color: C.text2 });
  });
  s.addNotes("Respuestas a las preguntas de escalabilidad. Diez mil asesores: todos los servicios son sin estado, el estado vive en Redis, así que escalo horizontalmente con KEDA según peticiones por segundo; Qdrant con réplicas; cuotas del proveedor LLM en varias regiones o capacidad reservada; el caché semántico absorbe preguntas repetidas de política y el streaming baja la latencia percibida. Si el proveedor LLM falla: reintento con backoff, circuit breaker y fallback escalonado: otro modelo, otro proveedor, modelo local y, en el peor caso, modo búsqueda que muestra los fragmentos citados sin generar; si nada alcanza, se escala a un humano. Las APIs con límite de 60 por minuto se manejan con Retry-After, backoff y caché de la ficha. Y si la calidad cae tras cambiar un prompt, el gate de CI lo detecta antes y la evaluación online después, con rollback de versión.");

  pres.addSection({ title: "Valor" });
  s = content("Valor", "KPIs instrumentados de punta a punta", "Cada métrica tiene una fuente de datos en la solución y un tablero en Grafana");
  const kp = [
    ["Negocio", HEX.accent1, [["AHT", "−20 %"], ["FCR", "+10 pp"], ["Escalamiento N2", "−15 %"], ["Retención", "medida"]]],
    ["Calidad LLM", HEX.accent2, [["Groundedness", "≥ 0,85"], ["Exactitud golden", "≥ 80 %"], ["Recall@k", "≥ 0,90"], ["Sin cita", "≤ 5 %"]]],
    ["Técnica", HEX.accent3, [["p95 primer token", "≤ 2 s"], ["p95 total", "≤ 8 s"], ["Disponibilidad", "≥ 99 %"], ["Frescura", "≤ 15 min"]]],
    ["Agentes", HEX.accent5, [["Éxito de tareas", "≥ 90 %"], ["Error de tools", "≤ 3 %"], ["Bucles / prohibidas", "0"], ["Costo por ejecución", "medido"]]],
    ["Modelo ML", HEX.accent4, [["F1 intención", "0,92"], ["AUC churn", "0,70 → 0,75"], ["Drift PSI", "alertado"], ["Reentreno", "PSI > 0,2"]]],
    ["DevOps", HEX.dk2, [["Cobertura", "≥ 70 %"], ["Lead time", "< 30 min"], ["Imagen", "slim"], ["CVEs críticas", "0"]]],
  ];
  kp.forEach((k, i) => {
    const x = 0.6 + i * 2.04;
    card(s, x, 1.75, 1.9, 4.3);
    box(s, x, 1.75, 1.9, 0.55, k[0], { fill: k[1], line: k[1], color: C.background1, bold: true, fs: 15 });
    k[2].forEach((m, j) => {
      const y = 2.5 + j * 0.88;
      text(s, m[0], x + 0.15, y, 1.65, 0.3, { fs: 12, color: C.text2 });
      text(s, m[1], x + 0.15, y + 0.3, 1.65, 0.45, { fs: 18, bold: true });
    });
  });
  text(s, "Negocio: piloto A/B con y sin copiloto · Calidad: golden + muestreo online con LLM-as-judge · Técnica y agentes: trazas OpenTelemetry · ML: MLflow + Evidently", 0.6, 6.25, 12.1, 0.55, { fs: 12, italic: true, color: C.text2 });
  s.addNotes("Componentes medibles. Negocio: el AHT y el FCR se miden en un piloto A/B, asesores con y sin copiloto, porque ese es el único modo honesto de atribuir el impacto. Calidad del LLM: exactitud contra el golden dataset por puntos clave, groundedness con LLM como juez, recall@k del retriever y porcentaje de respuestas sin cita. Técnica: latencia p95 al primer token y total, disponibilidad, costo por conversación y frescura de documentos. Agentes: éxito de tareas, errores de tools, bucles y acciones no permitidas. ML: F1 y AUC con drift. Todo llega a Grafana y a Phoenix.");

  // =========================================================
  // 14. BUSINESS CASE + FINOPS
  // =========================================================
  s = content("Valor", "Business case y FinOps", "Solo la palanca de AHT paga varias veces el costo de IA (supuestos a validar en piloto)");
  s.addChart(pres.charts.BAR, [{ name: "USD millones / año", labels: ["Capacidad liberada (AHT −20 %)", "Costo de IA (LLM)"], values: [1.27, 0.21] }], {
    x: 0.6, y: 1.75, w: 6.4, h: 3.6, barDir: "bar", chartColors: [HEX.accent3, HEX.accent1], varyColors: true,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '"US$"0.00"M"', dataLabelFontSize: 14, dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
    catAxisLabelColor: HEX.dk2, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", valAxisHidden: true, valAxisMaxVal: 1.7, valAxisMinVal: 0, catAxisOrientation: "maxMin",
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "Valor anual estimado vs costo de IA", titleFontSize: 14, titleColor: HEX.dk1, titleFontFace: "+mn-lt",
  });
  text(s, "Supuestos: 1.000 asesores · 40 interacciones/día · AHT 6 min · US$6/h · 264 días · 10,6 M conversaciones × US$0,02. FCR, escalamiento y retención suman valor adicional a medir en el piloto.", 0.6, 5.5, 6.4, 1.3, { fs: 12, italic: true, color: C.text2 });
  card(s, 7.4, 1.75, 5.3, 5.05, { fill: C.background2, line: HEX.lt2 });
  text(s, "Palancas de costo", 7.7, 1.95, 4.8, 0.4, { fs: 16, bold: true });
  const fin = [["FaRoute", "Ruteo por tarea", "80 % al tier económico, 20 % al tier alto"], ["FaMemory", "Caché semántico", "Preguntas de política repetidas sin llamar al LLM"], ["FaTags", "ML para intención", "Costo ≈ 0 en el paso más frecuente"], ["FaWallet", "Presupuestos", "Límite por usuario/día en LiteLLM y alerta de gasto"], ["FaReceipt", "Costo por traza", "Tokens × precio en cada llamada y por conversación"]];
  for (let i = 0; i < fin.length; i++) {
    const y = 2.5 + i * 0.85;
    await iconCircle(s, fin[i][0], 7.7, y, 0.5, HEX.dk2);
    text(s, fin[i][1], 8.35, y - 0.03, 4.2, 0.3, { fs: 14, bold: true });
    text(s, fin[i][2], 8.35, y + 0.27, 4.2, 0.4, { fs: 12, color: C.text2 });
  }
  s.addNotes("Business case referencial, con supuestos explícitos que el piloto valida. Con mil asesores, 40 interacciones diarias y un AHT de 6 minutos, bajar 20% libera unas 211 mil horas al año, alrededor de 1,27 millones de dólares en capacidad. El costo de IA con ruteo se estima en unos 0,21 millones. FCR, escalamiento y retención agregan valor que no estoy contando aquí. FinOps: ruteo por tarea, caché semántico, ML para la intención, presupuestos por usuario y el costo registrado en cada traza. Los precios se validan con la lista vigente del proveedor.");

  // =========================================================
  // 15. TRADE-OFFS Y ROADMAP
  // =========================================================
  s = content("Valor", "Decisiones clave y roadmap a escala Claro", "Decisiones reversibles y sin lock-in; del MVP a multicanal, multipaís y voz");
  const adr = [tblHead(["Decisión", "Sobre", "Por qué"])];
  [["Build orquestación, buy LLM", "Plataforma cerrada", "Control del flujo; servicios administrados"], ["Propietario + OSS", "Un solo modelo", "OpenAI por calidad; Llama/Mistral fallback"], ["Contenedores", "Serverless puro", "Modelos en memoria y SSE; ingesta por evento"], ["LangGraph", "CrewAI / cadena lineal", "Grafo explícito, checkpoints, HITL"], ["MCP para tools", "Funciones embebidas", "Desacople y reutilización"], ["LiteLLM", "SDK por proveedor", "Sin lock-in de proveedor LLM"], ["Qdrant", "pgvector / AI Search", "Híbrido nativo, OSS, portable"], ["Redis + MongoDB", "Un solo motor", "Latencia vs auditoría"]].forEach((r) => adr.push([{ text: r[0], options: { bold: true } }, r[1], r[2]]));
  s.addTable(adr, { x: 0.6, y: 1.75, w: 6.9, colW: [2.1, 1.8, 3.0], fontSize: 12, color: HEX.dk1, border: { type: "solid", pt: 0.5, color: "E2E4E8" }, rowH: 0.55, valign: "middle", fontFace: "Calibri" });
  const road = [["MVP", "Semanas 0–4", "Asesor web · RAG · tools · ML · CI/CD"], ["Piloto", "Mes 2–3", "200 asesores A/B · medir AHT/FCR · ajuste de prompts"], ["Escala", "Mes 4–6", "WhatsApp y chat cliente · red near real time · AKS/PTU"], ["Regional", "Mes 6+", "Multipaís por tenant · voz en tiempo real · fine-tuning"]];
  s.addShape(S.LINE, { x: 8.15, y: 1.95, w: 0, h: 4.6, line: { color: HEX.accent6, width: 1.5 } });
  road.forEach((r, i) => {
    const y = 1.8 + i * 1.25;
    s.addShape(S.OVAL, { x: 7.97, y: y + 0.12, w: 0.36, h: 0.36, fill: { color: i === 0 ? HEX.accent1 : HEX.dk2 }, line: { color: HEX.lt1, width: 1.5 } });
    text(s, r[0], 8.55, y, 1.6, 0.4, { fs: 16, bold: true, color: i === 0 ? C.accent1 : C.text1 });
    text(s, r[1], 10.1, y + 0.05, 2.6, 0.35, { fs: 12, italic: true, color: C.text2 });
    text(s, r[2], 8.55, y + 0.42, 4.15, 0.7, { fs: 13, color: C.text2 });
  });
  s.addNotes("Decisiones con su alternativa descartada. Build vs buy: construyo la orquestación, que es el diferencial y donde viven las reglas de negocio, y compro los modelos y servicios administrados. Propietario vs open source: OpenAI por calidad, modelos abiertos como fallback y opción on-premise. Contenedores vs serverless: los modelos cargados en memoria y el streaming piden contenedores; la ingesta sí es por evento. LangGraph por tener el flujo explícito y human-in-the-loop nativo. MCP para desacoplar las herramientas del agente. LiteLLM para no casarse con un proveedor. Qdrant por búsqueda híbrida nativa y open source. Redis más MongoDB por patrones de acceso. Phoenix porque Langfuse autohospedado requiere ClickHouse, Postgres y MinIO. Container Apps sobre AKS por operación. Roadmap: MVP en cuatro semanas, piloto A/B con 200 asesores, luego canales de cliente final y datos de red en tiempo real, y a nivel regional multipaís por tenant y voz. Para 10.000 asesores concurrentes: servicios sin estado con autoscaling, cuotas LLM multi-región y caché. Gracias, pasamos a la demo.");

  await pres.writeFile({ fileName: OUT });
  if (applyTheme) await applyTheme(OUT, THEME);
  console.log("OK " + OUT);
})().catch((e) => { console.error(e); process.exit(1); });
