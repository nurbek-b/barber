# Nginx with both SPAs baked in. Build context: repository root.
# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo
# manifests first: dependency layer is cached until a lockfile/package.json changes
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc tsconfig.base.json ./
COPY apps/miniapp/package.json apps/miniapp/
COPY apps/admin/package.json apps/admin/
COPY packages/api-client/package.json packages/api-client/
COPY packages/ui/package.json packages/ui/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY apps ./apps
COPY packages ./packages
# VITE_* values are public by design; no secrets ever reach the bundles
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN pnpm --filter @barber/miniapp build && pnpm --filter @barber/admin build

FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/nginx/templates /etc/nginx/templates
COPY infra/nginx/snippets /etc/nginx/snippets
COPY --from=build /repo/apps/miniapp/dist /usr/share/nginx/html/app
COPY --from=build /repo/apps/admin/dist /usr/share/nginx/html/admin
# nginx:alpine renders /etc/nginx/templates/*.template with envsubst at start (DOMAIN, ...)
ENV NGINX_ENVSUBST_FILTER="^(DOMAIN|API_UPSTREAM|BOT_UPSTREAM)$"
HEALTHCHECK --interval=15s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
