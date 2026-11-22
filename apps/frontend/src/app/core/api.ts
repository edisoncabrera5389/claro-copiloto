import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { API, Auth } from './auth';
import {
  EscalamientoAbierto,
  EventoChat,
  FichaCliente,
  Pendiente,
  TurnoGuardado,
} from './modelos';
import { LectorSse } from './sse';

@Injectable({ providedIn: 'root' })
export class ApiCopiloto {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(Auth);

  /** POST /chat con streaming SSE: produce los eventos a medida que llegan. */
  async *chat(mensaje: string, sesionId: string | null, senal?: AbortSignal): AsyncGenerator<EventoChat> {
    const r = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${this.auth.token() ?? ''}`,
      },
      body: JSON.stringify(sesionId ? { mensaje, sesion_id: sesionId } : { mensaje }),
      signal: senal,
    });
    if (r.status === 401) {
      this.auth.salir();
      throw new Error('La sesión expiró: ingresa de nuevo.');
    }
    if (r.status === 429) throw new Error('Demasiadas solicitudes: espera un minuto.');
    if (!r.ok || !r.body) throw new Error(`El servidor respondió ${r.status}.`);
    const lector = r.body.pipeThrough(new TextDecoderStream()).getReader();
    const sse = new LectorSse();
    for (;;) {
      const { value, done } = await lector.read();
      if (done) return;
      for (const e of sse.agregar(value)) {
        yield { tipo: e.evento, datos: JSON.parse(e.datos) } as EventoChat;
      }
    }
  }

  confirmar(propuestaId: string) {
    return firstValueFrom(
      this.http.post<{ estado: string; accion: string; resultado: unknown }>(
        `${API}/acciones/${propuestaId}/confirmar`,
        {},
      ),
    );
  }

  rechazar(propuestaId: string) {
    return firstValueFrom(this.http.post<{ estado: string }>(`${API}/acciones/${propuestaId}/rechazar`, {}));
  }

  feedback(turnoId: string, valor: 1 | -1, comentario?: string) {
    return firstValueFrom(
      this.http.post(`${API}/feedback`, { turno_id: turnoId, valor, comentario: comentario || null }),
    );
  }

  ficha(clienteId: string) {
    return firstValueFrom(this.http.get<FichaCliente>(`${API}/clientes/${clienteId}/ficha`));
  }

  escalar(sesionId: string, motivo?: string) {
    return firstValueFrom(
      this.http.post<{ escalamiento_id: string }>(`${API}/escalamientos`, { sesion_id: sesionId, motivo }),
    );
  }

  pendientes() {
    return firstValueFrom(this.http.get<Pendiente[]>(`${API}/acciones/pendientes`));
  }

  escalamientos() {
    return firstValueFrom(this.http.get<EscalamientoAbierto[]>(`${API}/escalamientos`));
  }

  atender(escalamientoId: string) {
    return firstValueFrom(this.http.post(`${API}/escalamientos/${escalamientoId}/atender`, {}));
  }

  conversacion(sesionId: string) {
    return firstValueFrom(this.http.get<TurnoGuardado[]>(`${API}/conversaciones/${sesionId}`));
  }
}
