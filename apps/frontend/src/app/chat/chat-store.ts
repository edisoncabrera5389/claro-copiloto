import { computed, inject, Injectable, signal } from '@angular/core';

import { ApiCopiloto } from '../core/api';
import { mensajeError } from '../core/auth';
import { EventoChat, Fuente, Propuesta, Resultado, ToolUsada } from '../core/modelos';

export type EstadoPropuesta = 'pendiente' | 'procesando' | 'ejecutada' | 'rechazada' | 'error';

export interface PropuestaVista extends Propuesta {
  estado: EstadoPropuesta;
  mensaje?: string;
}

export interface Turno {
  id: string; // local hasta que llega el turno_id del servidor
  pregunta: string;
  respuesta: string;
  paso: string | null;
  enCurso: boolean;
  tools: ToolUsada[];
  propuestas: PropuestaVista[];
  fuentes: Fuente[];
  resultado?: Resultado;
  error?: string;
  feedback?: 1 | -1;
}

let secuencia = 0;

/** Estado de la conversación del asesor (signals). Un turno a la vez; los eventos SSE lo van completando. */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(ApiCopiloto);
  private cancelar?: AbortController;

  readonly turnos = signal<Turno[]>([]);
  readonly sesionId = signal<string | null>(null);
  readonly fuenteActiva = signal<{ turno: string; n: number } | null>(null);
  readonly turnoSeleccionado = signal<string | null>(null);

  readonly enCurso = computed(() => this.turnos().some((t) => t.enCurso));
  /** Cliente de la conversación: el último que identificó el agente (los seguimientos lo heredan). */
  readonly clienteId = computed(
    () => [...this.turnos()].reverse().find((t) => t.resultado?.cliente_id)?.resultado?.cliente_id ?? null,
  );
  readonly riesgoChurn = computed(() => {
    const id = this.clienteId();
    return [...this.turnos()].reverse().find((t) => t.resultado?.cliente_id === id && t.resultado?.riesgo_churn)
      ?.resultado?.riesgo_churn ?? null;
  });
  /** Turno cuyas fuentes se muestran: el seleccionado o el último con fuentes. */
  readonly turnoFuentes = computed(() => {
    const ts = this.turnos();
    const sel = this.turnoSeleccionado();
    return ts.find((t) => t.id === sel) ?? [...ts].reverse().find((t) => t.fuentes.length) ?? null;
  });

  async enviar(texto: string): Promise<void> {
    const pregunta = texto.trim();
    if (!pregunta || this.enCurso()) return;
    let id = `local-${++secuencia}`;
    this.turnos.update((ts) => [
      ...ts,
      { id, pregunta, respuesta: '', paso: 'guardrails', enCurso: true, tools: [], propuestas: [], fuentes: [] },
    ]);
    this.turnoSeleccionado.set(null);
    this.cancelar = new AbortController();
    try {
      for await (const e of this.api.chat(pregunta, this.sesionId(), this.cancelar.signal)) {
        id = this.aplicar(id, e);
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        this.actualizar(id, (t) => ({ ...t, error: mensajeError(err) }));
      }
    } finally {
      this.actualizar(id, (t) => ({ ...t, enCurso: false, paso: null }));
    }
  }

  /** Aplica un evento al turno y devuelve su id (cambia al recibir `inicio`). */
  aplicar(id: string, e: EventoChat): string {
    switch (e.tipo) {
      case 'inicio':
        this.sesionId.set(e.datos.sesion_id);
        this.actualizar(id, (t) => ({ ...t, id: e.datos.turno_id }));
        return e.datos.turno_id;
      case 'estado':
        this.actualizar(id, (t) => ({ ...t, paso: e.datos.paso }));
        break;
      case 'token':
        this.actualizar(id, (t) => ({ ...t, respuesta: t.respuesta + e.datos.texto, paso: null }));
        break;
      case 'reiniciar':
        this.actualizar(id, (t) => ({ ...t, respuesta: '' }));
        break;
      case 'reemplazar':
        this.actualizar(id, (t) => ({ ...t, respuesta: e.datos.texto }));
        break;
      case 'tool':
        this.actualizar(id, (t) => ({ ...t, tools: [...t.tools, e.datos] }));
        break;
      case 'propuesta':
        this.actualizar(id, (t) => ({ ...t, propuestas: [...t.propuestas, { ...e.datos, estado: 'pendiente' }] }));
        break;
      case 'fuentes':
        this.actualizar(id, (t) => ({ ...t, fuentes: e.datos.fuentes }));
        break;
      case 'fin':
        this.actualizar(id, (t) => ({
          ...t,
          respuesta: e.datos.respuesta,
          fuentes: e.datos.fuentes,
          tools: e.datos.tools,
          resultado: e.datos,
          enCurso: false,
          paso: null,
        }));
        break;
      case 'error':
        this.actualizar(id, (t) => ({ ...t, error: e.datos.mensaje }));
        break;
    }
    return id;
  }

  async decidir(turnoId: string, propuesta: PropuestaVista, confirmar: boolean): Promise<void> {
    this.propuesta(turnoId, propuesta.propuesta_id, { estado: 'procesando', mensaje: undefined });
    try {
      if (confirmar) {
        await this.api.confirmar(propuesta.propuesta_id);
        this.propuesta(turnoId, propuesta.propuesta_id, { estado: 'ejecutada' });
      } else {
        await this.api.rechazar(propuesta.propuesta_id);
        this.propuesta(turnoId, propuesta.propuesta_id, { estado: 'rechazada' });
      }
    } catch (e) {
      this.propuesta(turnoId, propuesta.propuesta_id, { estado: 'error', mensaje: mensajeError(e) });
    }
  }

  async calificar(turnoId: string, valor: 1 | -1, comentario?: string): Promise<void> {
    await this.api.feedback(turnoId, valor, comentario);
    this.actualizar(turnoId, (t) => ({ ...t, feedback: valor }));
  }

  async escalar(motivo?: string): Promise<string> {
    const sesion = this.sesionId();
    if (!sesion) throw new Error('Primero describe el caso en el chat.');
    return (await this.api.escalar(sesion, motivo)).escalamiento_id;
  }

  verFuente(turno: string, n: number): void {
    this.turnoSeleccionado.set(turno);
    this.fuenteActiva.set({ turno, n });
  }

  nueva(): void {
    this.cancelar?.abort();
    this.turnos.set([]);
    this.sesionId.set(null);
    this.fuenteActiva.set(null);
    this.turnoSeleccionado.set(null);
  }

  private actualizar(id: string, fn: (t: Turno) => Turno): void {
    this.turnos.update((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
  }

  private propuesta(turnoId: string, pid: string, cambios: Partial<PropuestaVista>): void {
    this.actualizar(turnoId, (t) => ({
      ...t,
      propuestas: t.propuestas.map((p) => (p.propuesta_id === pid ? { ...p, ...cambios } : p)),
    }));
  }
}
