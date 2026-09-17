# Next.js web tier.
#
# Multi-stage, ending in `next start` over the standalone output rather than
# `next dev`. That is the whole reason four containers fit on an 8 GB machine:
# the dev server costs ~800 MB, the production server ~150 MB (ADR 0006).
#
# NEXT_TELEMETRY_DISABLED is set in every stage. It is the ONLY portable control -
# there is no `telemetry` key in next.config.mjs (Next rejects it as unrecognised
# and keeps posting), and `next telemetry disable` writes a machine-local file that
# does not travel with the repository. Security invariant 11 depends on this
# variable, so `tasks.py verify-compose` asserts it.

# --- dependencies ------------------------------------------------------------
FROM node:22-alpine AS deps
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- build -------------------------------------------------------------------
FROM node:22-alpine AS builder
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
RUN npm run build

# --- runtime -----------------------------------------------------------------
FROM node:22-alpine AS runner
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=3000
WORKDIR /app

RUN addgroup --system --gid 10002 ordin && \
    adduser  --system --uid 10002 --ingroup ordin ordin

# The standalone bundle carries only the modules actually reached at runtime.
COPY --from=builder --chown=ordin:ordin /app/.next/standalone ./
COPY --from=builder --chown=ordin:ordin /app/.next/static ./.next/static

USER ordin
EXPOSE 3000
CMD ["node", "server.js"]
