import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Auth } from './core/auth';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (auth.usuario(); as u) {
      <header class="barra">
        <span class="marca">Copiloto <small>· asesores</small></span>
        <nav>
          <a routerLink="/" routerLinkActive="activo" [routerLinkActiveOptions]="{ exact: true }">Asistente</a>
          @if (auth.esSupervisor()) {
            <a routerLink="/supervisor" routerLinkActive="activo">Supervisión</a>
          }
        </nav>
        <span class="usuario">
          {{ u.nombre }} <span class="rol">{{ u.rol }}</span>
          <button type="button" class="enlace" (click)="auth.salir()">Salir</button>
        </span>
      </header>
    }
    <main class="contenido"><router-outlet /></main>
  `,
})
export class App {
  protected readonly auth = inject(Auth);
}
