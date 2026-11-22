import {
  afterRenderEffect,
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { mensajeError } from '../core/auth';
import { ChatStore } from './chat-store';
import { FichaClienteView } from './ficha-cliente';
import { PanelFuentes } from './panel-fuentes';
import { TurnoView } from './turno';

const SUGERENCIAS = [
  '¿Cuánto cuesta el plan Hogar Fibra 500 y qué incluye?',
  'El cliente C-1004 quiere cancelar. ¿Qué oferta de retención le aplica?',
  'El cliente C-1013 llama a cancelar por fallas. ¿Cuál es el siguiente paso?',
  'El módem del cliente tiene la luz LOS en rojo desde hace 20 minutos. ¿Qué hago?',
];

@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, TurnoView, PanelFuentes, FichaClienteView],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './chat-page.html',
})
export class ChatPage {
  protected readonly store = inject(ChatStore);
  protected readonly sugerencias = SUGERENCIAS;
  protected texto = '';
  protected readonly escalando = signal(false);
  protected motivo = '';
  protected readonly aviso = signal<{ tipo: 'exito' | 'error'; texto: string } | null>(null);
  /** Acciones ejecutadas: al cambiar, la ficha del cliente se vuelve a consultar. */
  protected readonly ejecutadas = computed(
    () => this.store.turnos().flatMap((t) => t.propuestas).filter((p) => p.estado === 'ejecutada').length,
  );
  private readonly hilo = viewChild<ElementRef<HTMLElement>>('hilo');

  constructor() {
    afterRenderEffect(() => {
      this.store.turnos(); // desplazar al final con cada token
      const el = this.hilo()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  protected enviar(texto = this.texto): void {
    if (!texto.trim() || this.store.enCurso()) return;
    this.texto = '';
    void this.store.enviar(texto);
  }

  protected teclado(e: KeyboardEvent): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.enviar();
    }
  }

  protected async escalar(): Promise<void> {
    try {
      await this.store.escalar(this.motivo.trim() || undefined);
      this.aviso.set({ tipo: 'exito', texto: 'Caso escalado: quedó en la cola del supervisor.' });
      this.escalando.set(false);
      this.motivo = '';
    } catch (e) {
      this.aviso.set({ tipo: 'error', texto: mensajeError(e) });
    }
  }

  protected nueva(): void {
    this.store.nueva();
    this.aviso.set(null);
    this.escalando.set(false);
  }
}
