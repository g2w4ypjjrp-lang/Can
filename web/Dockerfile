# syntax=docker/dockerfile:1
# Web sitesi, müşteri paneli ve yönetim paneli (Next.js) — üretim imajı.
#
# İmaj ortamdan bağımsızdır: adresler ve alan adları çalışma anında ortam değişkenleriyle verilir
# (deploy/web.env.example). Gizli bilgi içermez. Süreç root olmayan kullanıcıyla çalışır.
#
#   docker build -t ati-web web/
#   docker run --env-file deploy/web.env -p 3000:3000 ati-web

FROM node:22.21.1-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

FROM node:22.21.1-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/robots.txt').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"
CMD ["sh", "-c", "exec node_modules/.bin/next start -H 0.0.0.0 -p \"$PORT\""]
