import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Auth, mensajeError } from '../core/auth';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <form class="login tarjeta" (ngSubmit)="entrar()">
      <h1>Copiloto de atención</h1>
      <p class="tenue">Asistente de IA para asesores: respuestas con fuente, datos del cliente y acciones con confirmación.</p>
      <label>
        Usuario
        <input name="usuario" [(ngModel)]="usuario" autocomplete="username" required />
      </label>
      <label>
        Contraseña
        <input name="password" type="password" [(ngModel)]="password" autocomplete="current-password" required />
      </label>
      @if (error()) {
        <p class="alerta error" role="alert">{{ error() }}</p>
      }
      <button type="submit" class="primario" [disabled]="cargando() || !usuario || !password">
        {{ cargando() ? 'Ingresando…' : 'Ingresar' }}
      </button>
      <p class="tenue pequeno">Demo: A-001 / A-002 (asesores) · SUP-001 (supervisora)</p>
    </form>
  `,
})
export class Login {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  protected usuario = '';
  protected password = '';
  protected readonly cargando = signal(false);
  protected readonly error = signal<string | null>(null);

  async entrar(): Promise<void> {
    this.cargando.set(true);
    this.error.set(null);
    try {
      await this.auth.entrar(this.usuario.trim(), this.password);
      await this.router.navigate([this.auth.esSupervisor() ? '/supervisor' : '/']);
    } catch (e) {
      this.error.set(mensajeError(e));
    } finally {
      this.cargando.set(false);
    }
  }
}
