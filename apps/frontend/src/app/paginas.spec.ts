import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { App } from './app';
import { ChatPage } from './chat/chat-page';
import { ChatStore } from './chat/chat-store';
import { FichaClienteView } from './chat/ficha-cliente';
import { PanelFuentes } from './chat/panel-fuentes';
import { ApiCopiloto } from './core/api';
import { Auth } from './core/auth';
import { FichaCliente } from './core/modelos';
import { Login } from './login/login';
import { SupervisorPage } from './supervisor/supervisor-page';

const esperar = () => new Promise((r) => setTimeout(r, 0));

const FICHA: FichaCliente = {
  cliente: {
    cliente_id: 'C-1004',
    nombre: 'Cliente Demo',
    ciudad: 'Bogotá',
    segmento: 'hogar',
    antiguedad_meses: 30,
    dias_mora: 45,
    estado: 'activo',
    valor_mensual_total: 169315,
    servicios: [{ plan: 'Hogar Fibra 500', tipo: 'hogar', valor_mensual: 109900, estado: 'activo' }],
    tickets_recientes: [{ fecha: '2026-11-01', categoria: 'soporte_tecnico' }, { fecha: '2025-01-01' }],
    ofertas_retencion_12m: [],
  },
  saldo: { saldo_pendiente: 169315, saldo_vencido: 50000, proxima_fecha_limite: '2026-11-25' },
  facturas: [{ factura_id: 'F-1', periodo: '2026-11', valor_total: 169315, estado: 'pendiente', fecha_limite_pago: '2026-11-25' }],
};

function api(cambios: Record<string, unknown> = {}) {
  return {
    ficha: vi.fn().mockResolvedValue(FICHA),
    pendientes: vi.fn().mockResolvedValue([
      { propuesta_id: 'p1', accion: 'aplicarAjuste', resumen: 'Ajuste $80.000', requiere_rol: 'supervisor', usuario: 'A-001', sesion_id: 's1', creada: 1_763_500_000 },
    ]),
    escalamientos: vi.fn().mockResolvedValue([
      { escalamiento_id: 'e1', sesion_id: 's1', turno_id: 't1', cliente_id: 'C-1004', motivo: 'Cliente molesto', usuario: 'A-001', fecha: '2026-11-18T10:00:00Z' },
    ]),
    conversacion: vi.fn().mockResolvedValue([{ turno_id: 't1', fecha: '', pregunta: '¿Oferta?', respuesta: 'RET-A [1]', ruta: 'agente', confianza: 0.9 }]),
    confirmar: vi.fn().mockResolvedValue({ estado: 'ejecutada' }),
    rechazar: vi.fn().mockResolvedValue({ estado: 'rechazada' }),
    atender: vi.fn().mockResolvedValue({ estado: 'atendido' }),
    escalar: vi.fn().mockResolvedValue({ escalamiento_id: 'e9' }),
    chat: vi.fn(async function* () {
      yield { tipo: 'inicio', datos: { sesion_id: 's1', turno_id: 't1' } };
      yield { tipo: 'token', datos: { texto: 'Hola [1]' } };
    }),
    ...cambios,
  };
}

function configurar(doble = api(), supervisor = false) {
  const auth = {
    usuario: signal({ id: 'SUP-001', rol: supervisor ? 'supervisor' : 'asesor', nombre: 'Demo' }),
    esSupervisor: signal(supervisor),
    entrar: vi.fn().mockResolvedValue(undefined),
    salir: vi.fn(),
    token: () => 't',
  };
  TestBed.configureTestingModule({
    providers: [provideRouter([]), { provide: ApiCopiloto, useValue: doble }, { provide: Auth, useValue: auth }],
  });
  vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  return { doble, auth };
}

describe('Login', () => {
  it('ingresa y lleva al supervisor a su cola', async () => {
    const { auth } = configurar(api(), true);
    const f = TestBed.createComponent(Login);
    const c = f.componentInstance as unknown as { usuario: string; password: string; entrar(): Promise<void> };
    c.usuario = ' SUP-001 ';
    c.password = 'clave';
    await c.entrar();
    expect(auth.entrar).toHaveBeenCalledWith('SUP-001', 'clave');
    expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/supervisor']);
  });

  it('muestra el error de credenciales', async () => {
    const { auth } = configurar();
    auth.entrar.mockRejectedValueOnce(new Error('Usuario o contraseña inválidos'));
    const f = TestBed.createComponent(Login);
    await (f.componentInstance as unknown as { entrar(): Promise<void> }).entrar();
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).querySelector('[role=alert]')?.textContent).toContain('inválidos');
  });
});

describe('App (barra)', () => {
  it('muestra el usuario y el acceso a Supervisión solo al supervisor', () => {
    configurar(api(), true);
    const f = TestBed.createComponent(App);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Supervisión');
    el.querySelector<HTMLButtonElement>('button.enlace')!.click();
    expect(TestBed.inject(Auth).salir).toHaveBeenCalled();
  });
});

describe('ChatPage', () => {
  it('envía una sugerencia, muestra la respuesta y permite escalar', async () => {
    const { doble } = configurar();
    const f = TestBed.createComponent(ChatPage);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    el.querySelector<HTMLButtonElement>('.sugerencias .chip')!.click();
    await esperar();
    f.detectChanges();
    expect(doble.chat).toHaveBeenCalled();
    expect(el.querySelector('.respuesta')?.textContent).toContain('Hola');

    const pagina = f.componentInstance as unknown as { motivo: string; escalar(): Promise<void>; teclado(e: KeyboardEvent): void };
    pagina.motivo = 'Cliente molesto';
    await pagina.escalar();
    f.detectChanges();
    expect(doble.escalar).toHaveBeenCalledWith('s1', 'Cliente molesto');
    expect(el.textContent).toContain('cola del supervisor');

    const tecla = new KeyboardEvent('keydown', { key: 'Enter' });
    const prevenir = vi.spyOn(tecla, 'preventDefault');
    pagina.teclado(tecla);
    expect(prevenir).toHaveBeenCalled();
    el.querySelectorAll<HTMLButtonElement>('.conversacion-cab button')[1].click(); // nueva conversación
    expect(TestBed.inject(ChatStore).turnos()).toEqual([]);
  });
});

describe('FichaClienteView', () => {
  it('muestra datos del CRM, marca mora > 30 días y cuenta tickets de 90 días', async () => {
    const { doble } = configurar();
    const f = TestBed.createComponent(FichaClienteView);
    f.componentRef.setInput('clienteId', 'C-1004');
    f.componentRef.setInput('riesgo', { nivel: 'alto', probabilidad: 0.6, factores: [] });
    f.detectChanges();
    await esperar();
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(doble.ficha).toHaveBeenCalledWith('C-1004');
    expect(el.textContent).toContain('Cliente Demo');
    expect(el.querySelectorAll('.critico').length).toBe(2); // mora 45 días y saldo vencido
    expect(el.textContent).toContain('1 tickets en 90 días');
    expect(el.textContent).toContain('Riesgo de abandono: alto');
  });

  it('informa si el CRM no responde', async () => {
    configurar(api({ ficha: vi.fn().mockRejectedValue(new Error('CRM no disponible')) }));
    const f = TestBed.createComponent(FichaClienteView);
    f.componentRef.setInput('clienteId', 'C-1004');
    f.detectChanges();
    await esperar();
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).querySelector('.alerta')?.textContent).toContain('CRM no disponible');
  });
});

describe('PanelFuentes', () => {
  it('lista las fuentes con versión y abre la que se citó', () => {
    configurar();
    const store = TestBed.inject(ChatStore);
    store.turnos.set([
      {
        id: 't1', pregunta: 'p', respuesta: 'r', paso: null, enCurso: false, tools: [], propuestas: [],
        fuentes: [{ n: 1, doc_id: 'c', titulo: 'Catálogo', version: '2.0', seccion: 'Planes', fuente: 'c.pdf', pagina: 3, relevancia: 0.8, citada: true, extracto: 'Fibra 500' }],
      },
    ]);
    store.verFuente('t1', 1);
    const f = TestBed.createComponent(PanelFuentes);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('.version')?.textContent).toContain('v2.0');
    expect(el.querySelector('details.activa')?.hasAttribute('open')).toBe(true);
    expect(el.querySelector('blockquote')?.textContent).toBe('Fibra 500');
  });
});

describe('SupervisorPage', () => {
  it('aprueba acciones, revisa la conversación y atiende escalamientos', async () => {
    const { doble } = configurar(api(), true);
    const f = TestBed.createComponent(SupervisorPage);
    f.detectChanges();
    await esperar();
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Aplicar ajuste en factura');
    expect(el.textContent).toContain('Cliente molesto');
    const boton = (texto: string) => [...el.querySelectorAll('button')].find((b) => b.textContent?.includes(texto))!;

    boton('Aprobar y ejecutar').click();
    await esperar();
    expect(doble.confirmar).toHaveBeenCalledWith('p1');
    boton('Rechazar').click();
    await esperar();
    expect(doble.rechazar).toHaveBeenCalledWith('p1');

    boton('Ver conversación').click();
    await esperar();
    f.detectChanges();
    expect(el.querySelector('.historial')?.textContent).toContain('RET-A');
    boton('Ocultar conversación').click();
    f.detectChanges();
    expect(el.querySelector('.historial')).toBeNull();

    boton('Marcar atendido').click();
    await esperar();
    f.detectChanges();
    expect(doble.atender).toHaveBeenCalledWith('e1');
    expect(el.textContent).toContain('atendido');
  });

  it('muestra el error si la API falla', async () => {
    configurar(api({ pendientes: vi.fn().mockRejectedValue(new Error('Solo un supervisor')) }), true);
    const f = TestBed.createComponent(SupervisorPage);
    f.detectChanges();
    await esperar();
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).querySelector('.alerta')?.textContent).toContain('Solo un supervisor');
  });
});
