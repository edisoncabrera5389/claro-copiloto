import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, firstValueFrom, throwError } from 'rxjs';

import { Usuario } from './modelos';

export const API = '/api'; // Nginx (y el proxy de ng serve) reenvían /api → servicio api:8000
const CLAVE = 'copiloto.sesion';

interface Sesion {
  token: string;
  usuario: Usuario;
  expira: number; // epoch ms, tomado del claim `exp` del JWT
}

/** JWT en sessionStorage (se borra al cerrar la pestaña). En producción: SSO corporativo (SAD). */
@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly sesion = signal<Sesion | null>(leer());

  readonly usuario = computed(() => this.sesion()?.usuario ?? null);
  readonly esSupervisor = computed(() => ['supervisor', 'admin'].includes(this.usuario()?.rol ?? ''));

  token(): string | null {
    const s = this.sesion();
    if (s && s.expira <= Date.now()) {
      this.salir();
      return null;
    }
    return s?.token ?? null;
  }

  async entrar(usuario: string, password: string): Promise<void> {
    const r = await firstValueFrom(
      this.http.post<{ access_token: string; usuario: Usuario }>(`${API}/auth/login`, { usuario, password }),
    );
    const s: Sesion = { token: r.access_token, usuario: r.usuario, expira: expiracion(r.access_token) };
    sessionStorage.setItem(CLAVE, JSON.stringify(s));
    this.sesion.set(s);
  }

  salir(): void {
    sessionStorage.removeItem(CLAVE);
    this.sesion.set(null);
    void this.router.navigate(['/login']);
  }
}

function leer(): Sesion | null {
  try {
    const s = JSON.parse(sessionStorage.getItem(CLAVE) ?? 'null') as Sesion | null;
    return s && s.expira > Date.now() ? s : null;
  } catch {
    return null;
  }
}

export function expiracion(jwt: string): number {
  try {
    const carga = JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return typeof carga.exp === 'number' ? carga.exp * 1000 : Date.now() + 3_600_000;
  } catch {
    return Date.now() + 3_600_000;
  }
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(Auth);
  const token = req.url.startsWith(API) && !req.url.endsWith('/auth/login') ? auth.token() : null;
  const conToken = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(conToken).pipe(
    catchError((e: HttpErrorResponse) => {
      if (e.status === 401 && token) auth.salir(); // token vencido o revocado
      return throwError(() => e);
    }),
  );
};

export const sesionActiva: CanActivateFn = () =>
  inject(Auth).token() ? true : inject(Router).createUrlTree(['/login']);

export const soloSupervisor: CanActivateFn = () =>
  inject(Auth).esSupervisor() ? true : inject(Router).createUrlTree(['/']);

/** Mensaje legible para el asesor a partir de un error HTTP de la API ({detail}) o de red. */
export function mensajeError(e: unknown): string {
  if (e instanceof HttpErrorResponse) {
    if (e.status === 0) return 'Sin conexión con el servidor.';
    const detalle = (e.error as { detail?: unknown } | null)?.detail;
    if (typeof detalle === 'string') return detalle;
    return `Error ${e.status}`;
  }
  return e instanceof Error ? e.message : 'Error inesperado';
}
