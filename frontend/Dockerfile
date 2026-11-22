FROM node:22-alpine AS base

# 1. Install dependencies
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# 2. Rebuild the source code
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV NEXT_PUBLIC_API_URL=http://localhost:8000/api
RUN npm run build

# 3. Production runner
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup -S dataextraction && adduser -S dataextraction -G dataextraction

COPY --from=builder /app/public ./public
COPY --from=builder --chown=dataextraction:dataextraction /app/.next/standalone ./
COPY --from=builder --chown=dataextraction:dataextraction /app/.next/static ./.next/static

USER dataextraction

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000/api/health 2>/dev/null || exit 1

CMD ["node", "server.js"]
