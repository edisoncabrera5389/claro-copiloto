import { Routes } from '@angular/router';

import { sesionActiva, soloSupervisor } from './core/auth';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./login/login').then((m) => m.Login), title: 'Copiloto · Ingreso' },
  {
    path: '',
    canActivate: [sesionActiva],
    loadComponent: () => import('./chat/chat-page').then((m) => m.ChatPage),
    title: 'Copiloto · Asistente',
  },
  {
    path: 'supervisor',
    canActivate: [sesionActiva, soloSupervisor],
    loadComponent: () => import('./supervisor/supervisor-page').then((m) => m.SupervisorPage),
    title: 'Copiloto · Supervisión',
  },
  { path: '**', redirectTo: '' },
];
