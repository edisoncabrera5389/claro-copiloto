import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal, untracked } from '@angular/core';

import { ApiCopiloto } from '../core/api';
import { mensajeError } from '../core/auth';
import { pesos } from '../core/formato';
import { FichaCliente, RiesgoChurn } from '../core/modelos';

/** Ficha del cliente identificado en la conversación (CRM + facturación vía MCP, sin documento/celular/correo). */
@Component({
  selector: 'app-ficha-cliente',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="tarjeta panel ficha">
      <h2>Cliente {{ clienteId() }}</h2>
      @if (cargando()) {
        <p class="tenue"><span class="giro" aria-hidden="true"></span>Consultando CRM y facturación…</p>
      } @else if (error()) {
        <p class="alerta error">{{ error() }}</p>
      } @else if (ficha(); as f) {
        @let c = f.cliente;
        <p class="nombre">{{ c.nombre }}</p>
        <p class="tenue pequeno">{{ c.segmento }} · {{ c.ciudad }} · {{ c.antiguedad_meses }} meses · {{ c.estado }}</p>
        <div class="cifras">
          <div><span class="tenue pequeno">Valor mensual</span><strong>{{ pesos(c.valor_mensual_total) }}</strong></div>
          <div [class.critico]="(c.dias_mora ?? 0) > 30">
            <span class="tenue pequeno">Mora</span><strong>{{ c.dias_mora ?? 0 }} días</strong>
          </div>
          @if (f.saldo; as s) {
            <div><span class="tenue pequeno">Saldo pendiente</span><strong>{{ pesos(s.saldo_pendiente) }}</strong></div>
            <div [class.critico]="s.saldo_vencido > 0">
              <span class="tenue pequeno">Vencido</span><strong>{{ pesos(s.saldo_vencido) }}</strong>
            </div>
          }
        </div>
        @if (riesgo(); as r) {
          <p class="churn" [attr.data-nivel]="r.nivel">Riesgo de abandono: <strong>{{ r.nivel }}</strong></p>
        }
        <h3>Servicios</h3>
        <ul class="lista">
          @for (s of c.servicios ?? []; track $index) {
            <li><span>{{ s.plan }} <span class="tenue">({{ s.tipo }}{{ s.estado !== 'activo' ? ', ' + s.estado : '' }})</span></span>
              <span>{{ pesos(s.valor_mensual) }}</span></li>
          }
        </ul>
        @if (f.facturas?.length) {
          <h3>Últimas facturas</h3>
          <ul class="lista">
            @for (fa of f.facturas; track fa.factura_id) {
              <li><span>{{ fa.periodo }} <span class="tenue">· {{ fa.estado }}</span></span><span>{{ pesos(fa.valor_total) }}</span></li>
            }
          </ul>
        }
        <p class="tenue pequeno">
          {{ tickets90() }} tickets en 90 días · {{ c.ofertas_retencion_12m?.length ? 'con' : 'sin' }} oferta de retención en 12 meses
        </p>
      }
    </section>
  `,
})
export class FichaClienteView {
  private readonly api = inject(ApiCopiloto);
  readonly clienteId = input.required<string>();
  readonly riesgo = input<RiesgoChurn | null>(null);
  /** Cambia tras confirmar una acción: vuelve a consultar la ficha. */
  readonly version = input(0);

  protected readonly ficha = signal<FichaCliente | null>(null);
  protected readonly cargando = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly pesos = pesos;
  protected readonly tickets90 = computed(() => {
    const desde = new Date('2026-11-18'); // fecha de referencia del caso
    desde.setDate(desde.getDate() - 90);
    return (this.ficha()?.cliente.tickets_recientes ?? []).filter((t) => new Date(t.fecha) >= desde).length;
  });

  constructor() {
    // El efecto depende SOLO del cliente y de la versión. cargar() lee y escribe `ficha`: sin untracked, esa
    // lectura volvía a disparar el efecto en cada respuesta (bucle de solicitudes → 429 "Demasiadas solicitudes").
    effect(() => {
      const id = this.clienteId();
      this.version();
      untracked(() => void this.cargar(id));
    });
  }

  private async cargar(id: string): Promise<void> {
    this.cargando.set(!this.ficha() || this.ficha()!.cliente.cliente_id !== id);
    this.error.set(null);
    try {
      this.ficha.set(await this.api.ficha(id));
    } catch (e) {
      this.error.set(mensajeError(e));
    } finally {
      this.cargando.set(false);
    }
  }
}
