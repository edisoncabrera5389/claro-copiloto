import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { API, Auth, authInterceptor, expiracion, mensajeError } from './auth';

function jwt(expSegundos: number): string {
  const carga = btoa(JSON.stringify({ sub: 'A-001', exp: expSegundos })).replace(/=+$/, '');
  return `x.${carga}.y`;
}

describe('Auth', () => {
  let auth: Auth;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    auth = TestBed.inject(Auth);
    http = TestBed.inject(HttpTestingController);
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => http.verify());

  async function entrar(rol = 'asesor', exp = Date.now() / 1000 + 3600) {
    const promesa = auth.entrar('A-001', 'clave');
    http.expectOne(`${API}/auth/login`).flush({ access_token: jwt(exp), usuario: { id: 'A-001', rol, nombre: 'Asesor' } });
    await promesa;
  }

  it('guarda la sesión en sessionStorage y agrega el token a las llamadas de la API', async () => {
    await entrar();
    expect(auth.usuario()?.id).toBe('A-001');
    expect(auth.esSupervisor()).toBe(false);
    void firstValueFrom(TestBed.inject(HttpClient).get(`${API}/acciones/pendientes`));
    const req = http.expectOne(`${API}/acciones/pendientes`);
    expect(req.request.headers.get('Authorization')).toMatch(/^Bearer x\./);
    req.flush([]);
  });

  it('un 401 de la API cierra la sesión', async () => {
    await entrar('supervisor');
    expect(auth.esSupervisor()).toBe(true);
    const llamada = firstValueFrom(TestBed.inject(HttpClient).get(`${API}/escalamientos`)).catch((e) => e);
    http.expectOne(`${API}/escalamientos`).flush({ detail: 'Token inválido' }, { status: 401, statusText: 'x' });
    expect(await llamada).toBeInstanceOf(HttpErrorResponse);
    expect(auth.usuario()).toBeNull();
  });

  it('un token vencido no se usa', async () => {
    await entrar('asesor', Date.now() / 1000 - 10);
    expect(auth.token()).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  it('lee la expiración del JWT y tolera tokens mal formados', () => {
    expect(expiracion(jwt(2_000_000_000))).toBe(2_000_000_000_000);
    expect(expiracion('basura')).toBeGreaterThan(Date.now());
  });

  it('traduce errores HTTP a mensajes legibles', () => {
    expect(mensajeError(new HttpErrorResponse({ status: 0 }))).toBe('Sin conexión con el servidor.');
    expect(mensajeError(new HttpErrorResponse({ status: 403, error: { detail: 'Requiere supervisor' } }))).toBe(
      'Requiere supervisor',
    );
    expect(mensajeError(new HttpErrorResponse({ status: 500, error: null }))).toBe('Error 500');
    expect(mensajeError(new Error('x'))).toBe('x');
  });
});
