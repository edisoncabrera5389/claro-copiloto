import { DecimalPipe, PercentPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { describirPaso, formatear } from '../core/formato';
import { ChatStore, Turno } from './chat-store';
import { PropuestaCard } from './propuesta';

const RUTAS: Record<string, { texto: string; clase: string }> = {
  escalar: { texto: 'Escalamiento', clase: 'ambar' },
  fuera_alcance: { texto: 'Fuera de alcance', clase: 'gris' },
  bloqueado: { texto: 'Bloqueado por seguridad', clase: 'rojo' },
};

@Component({
  selector: 'app-turno',
  imports: [PropuestaCard, FormsModule, DecimalPipe, PercentPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './turno.html',
})
export class TurnoView {
  protected readonly store = inject(ChatStore);
  readonly turno = input.required<Turno>();

  protected readonly bloques = computed(() => formatear(this.turno().respuesta));
  protected readonly paso = computed(() => (this.turno().paso ? describirPaso(this.turno().paso!) : null));
  protected readonly ruta = computed(() => RUTAS[this.turno().resultado?.ruta ?? ''] ?? null);
  protected readonly citadas = computed(
    () => new Set(this.turno().fuentes.filter((f) => f.citada).map((f) => f.n)),
  );
  protected readonly detalles = signal(false);
  protected readonly comentando = signal(false);
  protected comentario = '';

  protected async calificar(valor: 1 | -1): Promise<void> {
    if (valor === -1 && !this.comentando()) {
      this.comentando.set(true);
      return;
    }
    this.comentando.set(false);
    await this.store.calificar(this.turno().id, valor, this.comentario.trim() || undefined);
  }
}
