# syntax=docker/dockerfile:1
# Etapa 1: build de Angular (npm 11: el 10.9 falla al resolver los peers de Vitest).
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY angular.json tsconfig*.json ./
COPY public ./public
COPY src ./src
RUN npx ng build --configuration production

# Etapa 2: Nginx sin privilegios, solo los estáticos y la configuración.
# Trivy (gate de CI): la base 1.29-alpine tenía 1 CVE crítica y 56 altas; la estable 1.30.6 aún trae 4 críticas en
# nginx (corregidas en 1.30.7, sin imagen publicada). Mainline 1.31.7 + parches de Alpine: 0 críticas, 0 altas.
FROM nginxinc/nginx-unprivileged:1.31.7-alpine3.24
USER root
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/nginx.conf.template
COPY --from=build /app/dist/copiloto-front/browser /usr/share/nginx/html
USER 101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/salud || exit 1
# Sin los scripts del entrypoint (intentan escribir en /etc/nginx, que es de solo lectura).
ENV API_UPSTREAM=api:8000
ENTRYPOINT []
# La configuración se arma al iniciar en /tmp (la raíz es de solo lectura): solo se sustituye API_UPSTREAM.
CMD ["sh", "-c", "envsubst '${API_UPSTREAM}' < /etc/nginx/nginx.conf.template > /tmp/nginx.conf && exec nginx -c /tmp/nginx.conf -g 'daemon off;'"]
