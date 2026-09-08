# syntax=docker/dockerfile:1.7
# Root context is intentional: this repository uses npm workspaces and one root lockfile.
FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build
WORKDIR /src
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/package.json
RUN npm ci --no-audit --no-fund
COPY frontend ./frontend
# Remote app: no independent login and therefore no unused VITE_* auth arguments.
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.0-alpine@sha256:808f7846d21a9c94cf53833e8807a00a33fd0b65cc47fb05b79efe366c2d201f
USER root
RUN apk add --no-cache tzdata \
 && rm -f /etc/nginx/conf.d/default.conf \
 && chmod 1777 /etc/nginx/conf.d /tmp
COPY frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/docker-entrypoint.d/25-require-rendered-config.sh /docker-entrypoint.d/
COPY --from=build /src/frontend/dist /usr/share/nginx/html
RUN chmod 0555 /docker-entrypoint.d/25-require-rendered-config.sh
ENV TZ=Asia/Hong_Kong \
    NGINX_ENVSUBST_FILTER=^API_UPSTREAM$
USER 101:101
EXPOSE 3030
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
 CMD wget -q --spider http://127.0.0.1:3030/healthz
