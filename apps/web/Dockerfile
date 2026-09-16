# Web image (TASK-117) — the Next.js frontend as a production
# container. Multi-stage: the builder installs and builds (it needs
# the dev toolchain — TypeScript, Tailwind), the runner ships the
# built app and runs it as a non-root user.
#
# API_ORIGIN is set twice, deliberately (learned live in TASK-111):
# the build stage bakes the /api rewrite destination into the build
# output, and the server-side fetches (lib/server-api) read the
# variable again at `next start` runtime. Both must agree — the
# compose file passes the same value to both.

# syntax=docker/dockerfile:1
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG API_ORIGIN=http://localhost:8000
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=builder --chown=nextjs:nextjs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nextjs /app/.next ./.next
COPY --from=builder --chown=nextjs:nextjs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nextjs /app/next.config.ts ./next.config.ts
USER nextjs
EXPOSE 3000
# Runtime value for the server-side fetches — must match the build
# ARG above; compose passes the same to both.
ENV API_ORIGIN=http://localhost:8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["npm", "run", "start"]
