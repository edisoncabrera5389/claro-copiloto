import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';

import { ApiCopiloto } from '../core/api';
import { mensajeError } from '../core/auth';
import { ACCIONES } from '../core/formato';
import { EscalamientoAbierto, Pendiente, TurnoGuardado } from '../core/modelos';

const REFRESCO_MS = 10_000;

/** Cola del supervisor: acciones que exigen su aprobación (p. ej. ajustes > $50.000) y casos escalados. */
@Component({
  selector: 'app-supervisor-page',
  imports: [DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './supervisor-page.html',
})
export class SupervisorPage implements OnInit {
  private readonly api = inject(ApiCopiloto);
  protected readonly acciones = ACCIONES;
  protected readonly pendientes = signal<Pendiente[]>([]);
  protected readonly escalamientos = signal<EscalamientoAbierto[]>([]);
  protected readonly conversaciones = signal<Record<string, TurnoGuardado[]>>({});
  protected readonly procesando = signal<string | null>(null);
  protected readonly aviso = signal<{ tipo: 'exito' | 'error'; texto: string } | null>(null);

  constructor() {
    const id = setInterval(() => void this.refrescar(), REFRESCO_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(id));
  }

  ngOnInit(): void {
    void this.refrescar();
  }

  async refrescar(): Promise<void> {
    try {
      const [p, e] = await Promise.all([this.api.pendientes(), this.api.escalamientos()]);
      this.pendientes.set(p);
      this.escalamientos.set(e);
    } catch (err) {
      this.aviso.set({ tipo: 'error', texto: mensajeError(err) });
    }
  }

  protected async decidir(p: Pendiente, confirmar: boolean): Promise<void> {
    this.procesando.set(p.propuesta_id);
    try {
      if (confirmar) await this.api.confirmar(p.propuesta_id);
      else await this.api.rechazar(p.propuesta_id);
      this.aviso.set({ tipo: 'exito', texto: `${ACCIONES[p.accion] ?? p.accion}: ${confirmar ? 'ejecutada' : 'rechazada'}.` });
    } catch (e) {
      this.aviso.set({ tipo: 'error', texto: mensajeError(e) });
    } finally {
      this.procesando.set(null);
      await this.refrescar();
    }
  }

  protected async verConversacion(e: EscalamientoAbierto): Promise<void> {
    if (this.conversaciones()[e.sesion_id]) {
      this.conversaciones.update(({ [e.sesion_id]: _, ...resto }) => resto);
      return;
    }
    try {
      const turnos = await this.api.conversacion(e.sesion_id);
      this.conversaciones.update((c) => ({ ...c, [e.sesion_id]: turnos }));
    } catch (err) {
      this.aviso.set({ tipo: 'error', texto: mensajeError(err) });
    }
  }

  protected async atender(e: EscalamientoAbierto): Promise<void> {
    this.procesando.set(e.escalamiento_id);
    try {
      await this.api.atender(e.escalamiento_id);
      this.aviso.set({ tipo: 'exito', texto: 'Escalamiento marcado como atendido.' });
    } catch (err) {
      this.aviso.set({ tipo: 'error', texto: mensajeError(err) });
    } finally {
      this.procesando.set(null);
      await this.refrescar();
    }
  }

  protected fecha(epochSegundos: number): Date {
    return new Date(epochSegundos * 1000);
  }
}
