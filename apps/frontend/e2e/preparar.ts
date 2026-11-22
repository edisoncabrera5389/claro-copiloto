import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Toma la contraseña de demo de .env si no viene en el entorno y reinicia los mocks (estado limpio). */
export default async function preparar(): Promise<void> {
  if (!process.env['API_DEMO_PASSWORD']) {
    try {
      const env = readFileSync(resolve(__dirname, '../../../.env'), 'utf-8');
      const linea = env.split(/\r?\n/).find((l) => l.startsWith('API_DEMO_PASSWORD='));
      if (linea) process.env['API_DEMO_PASSWORD'] = linea.split('=').slice(1).join('=').replace(/^["']|["']$/g, '');
    } catch {
      /* sin .env: se exige la variable */
    }
  }
  if (!process.env['API_DEMO_PASSWORD']) throw new Error('Defina API_DEMO_PASSWORD para las pruebas E2E');
  await reiniciarMocks();
}

/** Los POST confirmados cambian el estado de los mocks (tickets, ajustes): se reinician antes y después. */
export async function reiniciarMocks(): Promise<void> {
  if (process.env['E2E_SIN_REINICIO']) return;
  execSync('docker compose restart crm-mock facturacion-mock', { cwd: resolve(__dirname, '../../..'), stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 4000));
}
