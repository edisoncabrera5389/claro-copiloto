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
FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist/copiloto-front/browser /usr/share/nginx/html
USER 101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/salud || exit 1
# Sin los scripts del entrypoint (intentan escribir en /etc/nginx, que es de solo lectura).
ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
