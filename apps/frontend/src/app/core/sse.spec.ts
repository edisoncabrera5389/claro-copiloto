import { LectorSse } from './sse';

describe('LectorSse', () => {
  it('lee eventos con CRLF (sse-starlette) e ignora los pings', () => {
    const l = new LectorSse();
    const eventos = l.agregar(': ping\r\n\r\nevent: token\r\ndata: {"texto":"Ho"}\r\n\r\n');
    expect(eventos).toEqual([{ evento: 'token', datos: '{"texto":"Ho"}' }]);
  });

  it('reconstruye un evento partido en varios trozos, incluso con CRLF cortado', () => {
    const l = new LectorSse();
    expect(l.agregar('event: fin\r\nda')).toEqual([]);
    expect(l.agregar('ta: {"a":1}\r')).toEqual([]);
    expect(l.agregar('\n\r\n')).toEqual([{ evento: 'fin', datos: '{"a":1}' }]);
  });

  it('une varias líneas data y usa "message" por defecto', () => {
    const l = new LectorSse();
    expect(l.agregar('data: uno\ndata: dos\n\nevent: x\n\n')).toEqual([{ evento: 'message', datos: 'uno\ndos' }]);
  });
});
