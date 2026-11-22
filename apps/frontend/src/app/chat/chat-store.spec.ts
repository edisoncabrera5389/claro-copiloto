import { TestBed } from '@angular/core/testing';

import { ApiCopiloto } from '../core/api';
import { EventoChat, Resultado } from '../core/modelos';
import { ChatStore } from './chat-store';

const fin = (cambios: Partial<Resultado> = {}): Resultado => ({
  turno_id: 't1',
  sesion_id: 's1',
  respuesta: 'Elegible [1].',
  confianza: 0.9,
  intencion: 'cancelacion',
  cliente_id: 'C-1004',
  riesgo_churn: { nivel: 'alto', probabilidad: 0.6, factores: [] },
  ruta: 'agente',
  motivo: null,
  fuentes: [
    { n: 1, doc_id: 'pol', titulo: 'Política', version: '3.1', seccion: '4', fuente: 'p.docx', pagina: null, relevancia: 0.8, citada: true },
  ],
  tools: [{ nombre: 'evaluarRetencion', ok: true }],
  propuestas: [],
  sin_cita: false,
  advertencias: [],
  modelo: 'alto',
  uso: { tokens_entrada: 1, tokens_salida: 1, costo_usd: 0.001, llamadas: 2 },
  latencias: { ttft_ms: 900, total_ms: 1500 },
  ...cambios,
});

function preparar(eventos: EventoChat[] | Error) {
  const api = {
    chat: vi.fn(async function* () {
      if (eventos instanceof Error) throw eventos;
      for (const e of eventos) yield e;
    }),
    confirmar: vi.fn().mockResolvedValue({ estado: 'ejecutada' }),
    rechazar: vi.fn().mockResolvedValue({ estado: 'rechazada' }),
    feedback: vi.fn().mockResolvedValue({}),
    escalar: vi.fn().mockResolvedValue({ escalamiento_id: 'e1' }),
  };
  TestBed.configureTestingModule({ providers: [{ provide: ApiCopiloto, useValue: api }] });
  return { store: TestBed.inject(ChatStore), api };
}

describe('ChatStore', () => {
  it('construye el turno con los eventos SSE y expone cliente, riesgo y fuentes', async () => {
    const { store } = preparar([
      { tipo: 'inicio', datos: { sesion_id: 's1', turno_id: 't1' } },
      { tipo: 'estado', datos: { paso: 'clasificando' } },
      { tipo: 'token', datos: { texto: 'Texto previo' } },
      { tipo: 'reiniciar', datos: {} },
      { tipo: 'tool', datos: { nombre: 'evaluarRetencion', ok: true } },
      { tipo: 'propuesta', datos: { propuesta_id: 'p1', accion: 'crearTicket', resumen: 'Visita', requiere_rol: 'asesor' } },
      { tipo: 'token', datos: { texto: 'Elegible ' } },
      { tipo: 'token', datos: { texto: '[1].' } },
      { tipo: 'fin', datos: fin() },
    ]);
    await store.enviar('C-1004 quiere cancelar');
    const t = store.turnos()[0];
    expect(t.id).toBe('t1');
    expect(t.respuesta).toBe('Elegible [1].');
    expect(t.enCurso).toBe(false);
    expect(t.propuestas[0].estado).toBe('pendiente');
    expect(store.sesionId()).toBe('s1');
    expect(store.clienteId()).toBe('C-1004');
    expect(store.riesgoChurn()?.nivel).toBe('alto');
    expect(store.turnoFuentes()?.fuentes[0].version).toBe('3.1');
  });

  it('envía la sesión en el siguiente turno y reemplaza el texto si la API lo pide', async () => {
    const { store, api } = preparar([
      { tipo: 'inicio', datos: { sesion_id: 's1', turno_id: 't2' } },
      { tipo: 'token', datos: { texto: 'algo' } },
      { tipo: 'reemplazar', datos: { texto: 'No encontré información suficiente.' } },
    ]);
    store.sesionId.set('s1');
    await store.enviar('¿y su saldo?');
    expect(api.chat).toHaveBeenCalledWith('¿y su saldo?', 's1', expect.any(AbortSignal));
    expect(store.turnos()[0].respuesta).toBe('No encontré información suficiente.');
  });

  it('muestra el error de red en el turno y no deja el turno colgado', async () => {
    const { store } = preparar(new Error('Demasiadas solicitudes: espera un minuto.'));
    await store.enviar('hola');
    expect(store.turnos()[0].error).toContain('Demasiadas');
    expect(store.enCurso()).toBe(false);
  });

  it('confirma y rechaza propuestas, califica y escala', async () => {
    const { store, api } = preparar([
      { tipo: 'inicio', datos: { sesion_id: 's1', turno_id: 't1' } },
      { tipo: 'propuesta', datos: { propuesta_id: 'p1', accion: 'crearTicket', resumen: 'x', requiere_rol: 'asesor' } },
      { tipo: 'propuesta', datos: { propuesta_id: 'p2', accion: 'aplicarAjuste', resumen: 'y', requiere_rol: 'asesor' } },
    ]);
    await store.enviar('caso');
    const [p1, p2] = store.turnos()[0].propuestas;
    await store.decidir('t1', p1, true);
    await store.decidir('t1', p2, false);
    expect(store.turnos()[0].propuestas.map((p) => p.estado)).toEqual(['ejecutada', 'rechazada']);
    api.confirmar.mockRejectedValueOnce(new Error('La propuesta ya fue atendida'));
    await store.decidir('t1', p1, true);
    expect(store.turnos()[0].propuestas[0]).toMatchObject({ estado: 'error', mensaje: 'La propuesta ya fue atendida' });

    await store.calificar('t1', -1, 'faltó el precio');
    expect(api.feedback).toHaveBeenCalledWith('t1', -1, 'faltó el precio');
    expect(store.turnos()[0].feedback).toBe(-1);
    expect(await store.escalar('cliente molesto')).toBe('e1');
  });

  it('no escala sin conversación y "nueva" limpia todo', async () => {
    const { store } = preparar([]);
    await expect(store.escalar()).rejects.toThrow('Primero describe el caso');
    store.sesionId.set('s1');
    store.verFuente('t1', 2);
    store.nueva();
    expect(store.sesionId()).toBeNull();
    expect(store.fuenteActiva()).toBeNull();
  });
});
