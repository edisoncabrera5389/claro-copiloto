import { PercentPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, ElementRef, inject, viewChildren } from '@angular/core';

import { ChatStore } from './chat-store';

/** Fuentes del turno con documento, VERSIÓN y sección: el asesor verifica de dónde salió cada dato. */
@Component({
  selector: 'app-panel-fuentes',
  imports: [PercentPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="tarjeta panel">
      <h2>Fuentes</h2>
      @if (store.turnoFuentes(); as t) {
        @for (f of t.fuentes; track f.n) {
          <details #fuente class="fuente" [attr.data-n]="f.n" [class.activa]="activa(t.id, f.n)" [class.no-citada]="!f.citada"
            [open]="activa(t.id, f.n)">
            <summary>
              <span class="num">{{ f.n }}</span>
              <span class="fuente-titulo">{{ f.titulo || f.fuente }}</span>
              <span class="insignia version">v{{ f.version }}</span>
            </summary>
            <p class="tenue pequeno">
              {{ f.fuente }}{{ f.seccion ? ' · ' + f.seccion : '' }}{{ f.pagina ? ' · pág. ' + f.pagina : '' }}
              · relevancia {{ f.relevancia | percent: '1.0-0' }}{{ f.citada ? ' · citada' : '' }}
            </p>
            @if (f.extracto) {
              <blockquote>{{ f.extracto }}</blockquote>
            }
          </details>
        } @empty {
          <p class="tenue">Esta respuesta no usó documentos.</p>
        }
      } @else {
        <p class="tenue">Las fuentes de cada respuesta aparecen aquí, con su versión vigente.</p>
      }
    </section>
  `,
})
export class PanelFuentes {
  protected readonly store = inject(ChatStore);
  private readonly fuentes = viewChildren<ElementRef<HTMLElement>>('fuente');

  constructor() {
    effect(() => {
      const a = this.store.fuenteActiva();
      const el = this.fuentes().find((f) => f.nativeElement.dataset['n'] === String(a?.n));
      el?.nativeElement.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
    });
  }

  protected activa(turno: string, n: number): boolean {
    const a = this.store.fuenteActiva();
    return a?.turno === turno && a.n === n;
  }
}
