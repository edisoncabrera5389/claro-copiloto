/**
 * Convierte la respuesta del LLM en bloques tipados que la plantilla pinta con @for.
 * No se usa innerHTML: el texto del modelo nunca se interpreta como HTML (sin riesgo de XSS).
 * Soporta lo que el prompt pide: párrafos, viñetas, **negrita** y citas [n] / [1, 2].
 */
export type Segmento = { tipo: 'texto' | 'negrita'; texto: string } | { tipo: 'cita'; n: number };

export interface Bloque {
  tipo: 'parrafo' | 'item';
  segmentos: Segmento[];
}

const VINETA = /^\s*(?:[-*•]|\d+[.)])\s+/;
const EN_LINEA = /\*\*([^*]+)\*\*|\[(\d+(?:\s*,\s*\d+)*)\]/g;

export function formatear(texto: string): Bloque[] {
  return texto
    .split('\n')
    .filter((l) => l.trim())
    .map((linea) => {
      const item = VINETA.test(linea);
      return { tipo: item ? 'item' : 'parrafo', segmentos: segmentar(linea.replace(VINETA, '').trim()) };
    });
}

export function segmentar(linea: string): Segmento[] {
  const salida: Segmento[] = [];
  let desde = 0;
  for (const m of linea.matchAll(EN_LINEA)) {
    if (m.index > desde) salida.push({ tipo: 'texto', texto: linea.slice(desde, m.index) });
    if (m[1] !== undefined) salida.push({ tipo: 'negrita', texto: m[1] });
    else for (const n of m[2].split(',')) salida.push({ tipo: 'cita', n: Number(n.trim()) });
    desde = m.index + m[0].length;
  }
  if (desde < linea.length) salida.push({ tipo: 'texto', texto: linea.slice(desde) });
  return salida;
}

const COP = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 });

export function pesos(valor: number | null | undefined): string {
  return valor == null ? '—' : COP.format(valor);
}

export const ACCIONES: Partial<Record<string, string>> = {
  crearTicket: 'Crear ticket',
  registrarOfertaRetencion: 'Registrar oferta de retención',
  aplicarAjuste: 'Aplicar ajuste en factura',
};

export const PASOS: Record<string, string> = {
  guardrails: 'Revisando la solicitud',
  clasificando: 'Entendiendo la consulta',
  escalando: 'Preparando el escalamiento',
  pensando: 'Redactando la respuesta',
  'buscando en fuentes': 'Buscando en las fuentes oficiales',
};

export function describirPaso(paso: string): string {
  if (PASOS[paso]) return PASOS[paso];
  if (paso.startsWith('consultando ')) return `Consultando ${paso.slice(12)}`;
  if (paso.startsWith('paso ')) return 'Analizando los datos';
  return paso;
}
