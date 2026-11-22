import { describirPaso, formatear, pesos, segmentar } from './formato';

describe('formatear', () => {
  it('separa párrafos y viñetas y reconoce negrita y citas múltiples', () => {
    const bloques = formatear('Elegible a **RET-A** [1].\n\n- 30 % por 6 meses [1, 2]\n2. Visita técnica');
    expect(bloques.map((b) => b.tipo)).toEqual(['parrafo', 'item', 'item']);
    expect(bloques[0].segmentos).toEqual([
      { tipo: 'texto', texto: 'Elegible a ' },
      { tipo: 'negrita', texto: 'RET-A' },
      { tipo: 'texto', texto: ' ' },
      { tipo: 'cita', n: 1 },
      { tipo: 'texto', texto: '.' },
    ]);
    expect(bloques[1].segmentos.filter((s) => s.tipo === 'cita')).toEqual([
      { tipo: 'cita', n: 1 },
      { tipo: 'cita', n: 2 },
    ]);
  });

  it('nunca interpreta HTML: el texto pasa tal cual como segmento', () => {
    expect(segmentar('<img src=x onerror=alert(1)>')).toEqual([
      { tipo: 'texto', texto: '<img src=x onerror=alert(1)>' },
    ]);
  });

  it('no confunde corchetes que no son citas', () => {
    expect(segmentar('[DOCUMENTO] y (CRM)')).toEqual([{ tipo: 'texto', texto: '[DOCUMENTO] y (CRM)' }]);
  });
});

describe('utilidades', () => {
  it('formatea pesos colombianos sin decimales', () => {
    expect(pesos(109900).replace(/\s/g, ' ')).toMatch(/\$ ?109\.900/);
    expect(pesos(null)).toBe('—');
  });

  it('describe los pasos del agente en lenguaje del asesor', () => {
    expect(describirPaso('clasificando')).toBe('Entendiendo la consulta');
    expect(describirPaso('consultando obtenerCliente')).toBe('Consultando obtenerCliente');
    expect(describirPaso('paso 3')).toBe('Analizando los datos');
  });
});
