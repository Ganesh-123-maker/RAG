FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps

# ─────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# BACKEND_URL is consumed only by next.config.js rewrites at build time;
# the actual value is overridden at runtime via docker-compose ENV.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL

RUN npm run build

# ─────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Copy the standalone output and public assets. NOTE: frontend/public/
# must exist in the repo (it holds only a .gitkeep placeholder) or this
# COPY fails the build -- that was a Phase A fresh-clone breakage.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.js ./next.config.js

RUN chown -R node:node /app

EXPOSE 3000

USER node

CMD ["npm", "run", "start"]
