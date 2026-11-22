import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';

import { Auth } from '../core/auth';
import { ACCIONES } from '../core/formato';
import { PropuestaVista } from './chat-store';

/** Acción con efecto: el agente solo la PROPONE; ejecuta quien confirma (API firma el token para el MCP). */
@Component({
  selector: 'app-propuesta',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let p = propuesta();
    <div class="propuesta" [attr.data-estado]="p.estado">
      <div class="propuesta-cab">
        <strong>{{ titulo() }}</strong>
        @if (p.requiere_rol === 'supervisor') {
          <span class="insignia ambar">Requiere supervisor</span>
        }
      </div>
      <p>{{ p.resumen }}</p>
      @switch (p.estado) {
        @case ('ejecutada') {
          <p class="exito">✔ Ejecutada y registrada en auditoría.</p>
        }
        @case ('rechazada') {
          <p class="tenue">Rechazada: no se ejecutó.</p>
        }
        @default {
          @if (puedeConfirmar()) {
            <div class="acciones">
              <button type="button" class="primario" [disabled]="p.estado === 'procesando'" (click)="decidir.emit(true)">
                {{ p.estado === 'procesando' ? 'Ejecutando…' : 'Confirmar' }}
              </button>
              <button type="button" [disabled]="p.estado === 'procesando'" (click)="decidir.emit(false)">Rechazar</button>
            </div>
          } @else {
            <p class="tenue">En la cola de aprobación del supervisor.</p>
          }
          @if (p.mensaje) {
            <p class="alerta error" role="alert">{{ p.mensaje }}</p>
          }
        }
      }
    </div>
  `,
})
export class PropuestaCard {
  private readonly auth = inject(Auth);
  readonly propuesta = input.required<PropuestaVista>();
  readonly decidir = output<boolean>();
  protected readonly titulo = computed(() => ACCIONES[this.propuesta().accion] ?? this.propuesta().accion);
  protected readonly puedeConfirmar = computed(
    () => this.propuesta().requiere_rol !== 'supervisor' || this.auth.esSupervisor(),
  );
}
