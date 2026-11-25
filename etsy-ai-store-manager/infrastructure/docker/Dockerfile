# syntax=docker/dockerfile:1.7
# Multi-target image for the monorepo: --target api | worker | web | migrate
ARG NODE_IMAGE=node:22.20-alpine

FROM ${NODE_IMAGE} AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1
# Optional corporate/egress-proxy CA: docker build --secret id=extra_ca,src=ca.crt ...
# (used only during the build steps that download packages; never copied into the image)
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    corepack enable && corepack prepare pnpm@10.28.0 --activate
WORKDIR /repo

FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/api/package.json apps/api/
COPY apps/worker/package.json apps/worker/
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
COPY packages/integrations/package.json packages/integrations/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    pnpm install --frozen-lockfile

FROM deps AS build
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_SITE_URL
COPY tsconfig.base.json ./
COPY packages ./packages
COPY apps ./apps
RUN pnpm build:packages \
 && pnpm --filter @esm/api build \
 && pnpm --filter @esm/worker build \
 && pnpm --filter @esm/web build \
 && pnpm deploy --filter @esm/api --prod --legacy /out/api \
 && pnpm deploy --filter @esm/worker --prod --legacy /out/worker

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
USER app
# PID 1 signal handling: docker-compose uses `init: true`

FROM runtime AS api
COPY --from=build --chown=app:app /out/api ./
COPY --from=build --chown=app:app /repo/apps/api/dist ./dist
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:4000/api/v1/health || exit 1
CMD ["node", "--enable-source-maps", "dist/main.js"]

FROM runtime AS worker
COPY --from=build --chown=app:app /out/worker ./
COPY --from=build --chown=app:app /repo/apps/worker/dist ./dist
CMD ["node", "--enable-source-maps", "dist/main.js"]

FROM runtime AS web
ENV PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=app:app /repo/apps/web/.next/standalone ./
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "apps/web/server.js"]

FROM runtime AS migrate
COPY --from=build --chown=app:app /repo/node_modules/.pnpm/pg@8.23.1/node_modules ./node_modules
COPY --chown=app:app packages/database ./packages/database
COPY --chown=app:app infrastructure/scripts/migrate.mjs ./infrastructure/scripts/migrate.mjs
CMD ["node", "infrastructure/scripts/migrate.mjs"]
