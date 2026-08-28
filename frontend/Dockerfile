# ============================================================
# AEGIS — Dockerfile del Frontend (Next.js Standalone)
# Multi-stage build optimizado para producción.
#
# Seguridad aplicada:
# - Proceso corre como usuario no-root 'nextjs' (UID 1001)
# - Imagen base alpina ultra-reducida
# ============================================================

# --- Stage 1: Dependencias ---
FROM node:20-alpine AS deps
# libc6-compat es necesaria para algunas dependencias nativas en Alpine
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Instalar dependencias de forma limpia y exacta basadas en el lockfile
COPY package.json package-lock.json ./
RUN npm ci

# --- Stage 2: Compilación ---
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Argumento para inyectar la URL de la API durante la build
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# Deshabilitar telemetría durante la build
ENV NEXT_TELEMETRY_DISABLED=1

# Compilar la aplicación Next.js
RUN npm run build

# --- Stage 3: Runtime ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV NEXT_TELEMETRY_DISABLED=1

# Crear usuario y grupo de sistema sin privilegios root
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copiar assets públicos
COPY --from=builder /app/public ./public

# Crear el directorio .next y ajustar ownership para la caché de Next.js
RUN mkdir .next
RUN chown nextjs:nodejs .next

# Copiar el output standalone compilado por Next.js
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Cambiar al usuario no-root
USER nextjs

# Puerto expuesto
EXPOSE 3000

# Servidor Next.js (server.js se genera automáticamente con output: standalone)
CMD ["node", "server.js"]
