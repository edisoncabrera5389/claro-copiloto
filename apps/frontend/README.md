# Frontend · interfaz del asesor y del supervisor

**Tecnología:** Angular 21 LTS (standalone, signals, zoneless, control flow nativo) · Nginx sin privilegios · Vitest · Playwright · ESLint (angular-eslint + accesibilidad)
**Fases del caso:** 3
**Estado:** ✅ asesor y supervisor completos, probados de punta a punta contra la API real

## Qué hace

| Vista | Funciones |
|---|---|
| **Asistente** (asesor) | Chat con **streaming** (los tokens llegan en vivo con el paso del agente: "Consultando obtenerCliente…") · **citas [n] clicables** que abren la fuente con documento, **versión**, sección, relevancia y extracto · **ficha del cliente** (CRM + facturación: plan, valor, mora, saldo, facturas, tickets) cuando la conversación identifica un `C-XXXX` · **propuestas de acciones** con Confirmar/Rechazar (las que exigen supervisor no se pueden confirmar aquí) · **riesgo de churn** como señal de prioridad · 👍/👎 con comentario · **Escalar a supervisor** · detalles técnicos por turno (ruta, intención, modelo, TTFT, costo) |
| **Supervisión** | Acciones por aprobar (p. ej. ajustes > $50.000) · casos escalados con el cliente, el motivo y la conversación completa · marcar atendido · se actualiza cada 10 s |

El modo "cliente final" (opcional en el caso) queda como siguiente paso.

## Decisiones

| Decisión | Por qué |
|---|---|
| **Angular 21 LTS** (el SAD decía 18) | Angular 18 ya no tiene soporte de seguridad; Angular 22 exige Node ≥ 22.22 y la máquina de demo tiene 22.14. La 21 tiene soporte LTS hasta mayo de 2027 y las mismas APIs |
| **SSE sobre `fetch`** ([sse.ts](src/app/core/sse.ts)) | `EventSource` no permite POST ni la cabecera `Authorization`. El lector tolera eventos partidos entre lecturas y el CRLF de sse-starlette |
| **Sin `innerHTML`** ([formato.ts](src/app/core/formato.ts)) | La respuesta del LLM se convierte en bloques tipados (texto, negrita, cita) que la plantilla pinta: el texto del modelo nunca se interpreta como HTML (sin XSS, verificado en pruebas) |
| **Mismo origen** | Nginx sirve el front y reenvía `/api/` → `api:8000` (sin CORS). SSE sin buffer (`proxy_buffering off`) para que cada token llegue al instante |
| **CSP estricta** | `script-src 'self'`, `frame-ancestors 'none'`, `connect-src 'self'` + `nosniff`, `Referrer-Policy`, `Permissions-Policy`. Por eso se desactivó `inlineCritical`: Angular carga el CSS diferido con un `onload` en línea que la CSP bloquea (detectado en las capturas de las pruebas) |
| **Sesión** | JWT en `sessionStorage` (se borra al cerrar la pestaña), expiración leída del claim `exp`; un 401 cierra la sesión. En producción: SSO corporativo |
| **Logs de Nginx sin query ni cuerpo** | Pueden traer datos del cliente (Ley 1581) |
| **Upstream configurable** | `API_UPSTREAM` (por defecto `api:8000` en compose; `api:80` en Azure Container Apps) se aplica al iniciar con `envsubst` en `/tmp`, porque la raíz es de solo lectura. El proxy envía `Host: api`, que es lo que necesita el Envoy de Container Apps para enrutar |
| **`/api/metrics` bloqueado** | Las métricas de Prometheus solo se leen en la red interna; desde el navegador responde 404 |

## Ejecución

**Con Docker** (lo normal): `docker compose up -d frontend` → http://localhost:8080 (usuarios A-001, A-002, SUP-001 con `API_DEMO_PASSWORD`).
Imagen multi-stage de 82 MB: build con Node 24, servida por `nginx-unprivileged` (uid 101, puerto 8080), raíz de solo lectura.

**Desarrollo** (recarga en caliente, con la API en `localhost:8000`):

```powershell
cd apps/frontend
npx -y npm@11 ci      # npm 10.9 falla al resolver los peers de Vitest ("reading 'edgesOut'")
npm start             # http://localhost:4200, proxy /api → localhost:8000 (proxy.conf.json)
```

## Pruebas

```powershell
npm test              # Vitest: 30 pruebas
npm run test:cov      # cobertura sobre TODO src/app: 94 % de líneas (gate 70 %)
npm run lint          # ESLint + reglas de accesibilidad en plantillas
npm run e2e           # Playwright contra docker compose (LLM real, ~US$ 0,02): 4 flujos
```

> En Windows, correr las pruebas desde una ruta con la unidad en mayúscula (`C:\...`): con `c:\...` Vitest carga dos
> instancias y falla con "Vitest failed to find the runner".

- **Unitarias**: lector SSE (trozos partidos, CRLF, pings), formateador (citas múltiples, HTML inerte), store del chat
  (todos los eventos, errores de red, propuestas, feedback, escalamiento), autenticación (token, 401, expiración) y las
  páginas (login, chat, ficha, fuentes, supervisión, permisos por rol).
- **E2E** ([e2e/copiloto.spec.ts](e2e/copiloto.spec.ts)): RAG con cita y versión · retención GQ-28 con ficha y visita
  técnica confirmada · ajuste > $50.000 que el asesor no puede confirmar → escala → la supervisora aprueba · inyección
  bloqueada. Reinicia los mocks antes y después para partir siempre de los mismos datos.
- Las E2E encontraron un bug real en la API: si el cliente se desconectaba a mitad del turno, el turno se cancelaba y no
  quedaba auditado (corregido con `asyncio.shield`, ver [apps/api](../api/README.md)).
