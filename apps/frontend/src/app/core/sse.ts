/**
 * Lector de Server-Sent Events sobre `fetch` (EventSource no permite POST ni la cabecera Authorization).
 * Acepta trozos arbitrarios: un evento puede llegar partido en varios `read()` y sse-starlette separa con CRLF.
 */
export interface EventoSse {
  evento: string;
  datos: string;
}

export class LectorSse {
  private buffer = '';

  agregar(trozo: string): EventoSse[] {
    this.buffer += trozo;
    // Un "\r" al final puede ser la mitad de un CRLF: se normaliza en el siguiente trozo.
    const pendienteCr = this.buffer.endsWith('\r');
    const cuerpo = (pendienteCr ? this.buffer.slice(0, -1) : this.buffer).replace(/\r\n?/g, '\n');
    const bloques = cuerpo.split('\n\n');
    this.buffer = bloques.pop()! + (pendienteCr ? '\r' : '');
    return bloques.map(leerBloque).filter((e): e is EventoSse => e !== null);
  }
}

function leerBloque(bloque: string): EventoSse | null {
  let evento = 'message';
  const datos: string[] = [];
  for (const linea of bloque.split('\n')) {
    if (!linea || linea.startsWith(':')) continue; // comentario (ping de keep-alive)
    const p = linea.indexOf(':');
    const campo = p < 0 ? linea : linea.slice(0, p);
    let valor = p < 0 ? '' : linea.slice(p + 1);
    if (valor.startsWith(' ')) valor = valor.slice(1);
    if (campo === 'event') evento = valor;
    else if (campo === 'data') datos.push(valor);
  }
  return datos.length ? { evento, datos: datos.join('\n') } : null;
}
