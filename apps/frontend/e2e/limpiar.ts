import { reiniciarMocks } from './preparar';

/** Deja los mocks como al inicio: la siguiente demo o prueba parte de los mismos datos. */
export default async function limpiar(): Promise<void> {
  await reiniciarMocks();
}
