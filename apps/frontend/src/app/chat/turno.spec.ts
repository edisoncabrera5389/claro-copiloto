import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ApiCopiloto } from '../core/api';
import { Auth } from '../core/auth';
import { ChatStore, Turno } from './chat-store';
import { TurnoView } from './turno';

function montar(turno: Partial<Turno>, supervisor = false) {
  TestBed.configureTestingModule({
    providers: [
      { provide: ApiCopiloto, useValue: {} },
      { provide: Auth, useValue: { esSupervisor: signal(supervisor) } },
    ],
  });
  const f = TestBed.createComponent(TurnoView);
  f.componentRef.setInput('turno', {
    id: 't1',
    pregunta: '¿Precio?',
    respuesta: '',
    paso: null,
    enCurso: false,
    tools: [],
    propuestas: [],
    fuentes: [],
    ...turno,
  });
  f.detectChanges();
  return { f, el: f.nativeElement as HTMLElement, store: TestBed.inject(ChatStore) };
}

describe('TurnoView', () => {
  it('pinta citas como botones que abren la fuente y no interpreta HTML del modelo', () => {
    const { el, store } = montar({
      respuesta: 'Cuesta **$109.900** [1].\n- <img src=x onerror=alert(1)>',
      fuentes: [{ n: 1, doc_id: 'c', titulo: 'Catálogo', version: '2.0', seccion: null, fuente: 'c.pdf', pagina: 1, relevancia: 0.9, citada: true }],
    });
    expect(el.querySelector('strong')?.textContent).toBe('$109.900');
    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>');
    const cita = el.querySelector<HTMLButtonElement>('button.cita')!;
    expect(cita.classList).toContain('valida');
    cita.click();
    expect(store.fuenteActiva()).toEqual({ turno: 't1', n: 1 });
  });

  it('muestra el paso del agente mientras responde', () => {
    const { el } = montar({ enCurso: true, paso: 'consultando obtenerCliente' });
    expect(el.querySelector('.paso')?.textContent).toContain('Consultando obtenerCliente');
  });

  it('el asesor no puede confirmar una acción que exige supervisor; el supervisor sí', () => {
    const propuesta = { propuesta_id: 'p1', accion: 'aplicarAjuste', resumen: 'Ajuste $80.000', requiere_rol: 'supervisor' as const, estado: 'pendiente' as const };
    const asesor = montar({ propuestas: [propuesta] });
    expect(asesor.el.textContent).toContain('Requiere supervisor');
    expect(asesor.el.textContent).toContain('cola de aprobación');
    expect([...asesor.el.querySelectorAll('button')].some((b) => b.textContent?.includes('Confirmar'))).toBe(false);
    TestBed.resetTestingModule();
    const sup = montar({ propuestas: [propuesta] }, true);
    expect([...sup.el.querySelectorAll('button')].some((b) => b.textContent?.includes('Confirmar'))).toBe(true);
  });
});
