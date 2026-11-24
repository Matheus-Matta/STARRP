# Contexto de build = RAIZ do monorepo (o PDV web usa o núcleo fiscal de shared/):
#   docker build -f frontend/Dockerfile -t starrp-web .
# O que entra no contexto está em frontend/Dockerfile.dockerignore.

# 1) Build do app (tipos conferidos pelo vue-tsc: não compila, não sobe).
FROM node:22-alpine AS build
WORKDIR /repo/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY shared/ /repo/shared/
COPY frontend/ ./
# Versão da tag (frontend-v1.0.1 → 1.0.1): fica em /version.txt (confere o que está no ar).
ARG APP_VERSION=dev
RUN npm run build && echo "${APP_VERSION}" > dist/version.txt

# 2) Só o Caddy e os arquivos prontos (sem Node na imagem final).
FROM caddy:2.11-alpine
COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /repo/frontend/dist /srv/app
# Fotos enviadas: monte aqui o mesmo volume do MEDIA_ROOT do backend (/app/media).
RUN mkdir -p /srv/media
EXPOSE 80 443 443/udp
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:2019/config/ > /dev/null || exit 1
