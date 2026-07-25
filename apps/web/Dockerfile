# Sentinel Planner web app.
# Build context: repository root (the npm workspace needs packages/shared-schemas).
FROM node:22-alpine AS deps

WORKDIR /srv
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/shared-schemas/package.json ./packages/shared-schemas/package.json
RUN npm ci

# --- Development --------------------------------------------------------------
FROM deps AS dev
WORKDIR /srv
COPY . .
WORKDIR /srv/apps/web
EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- Production ---------------------------------------------------------------
FROM deps AS builder
WORKDIR /srv
COPY . .
RUN npm run build --workspace @sentinel/web

FROM node:22-alpine AS prod
WORKDIR /srv
ENV NODE_ENV=production
COPY --from=builder /srv /srv
WORKDIR /srv/apps/web
RUN addgroup --system --gid 1001 sentinel && adduser --system --uid 1001 sentinel \
    && chown -R sentinel:sentinel /srv
USER sentinel
EXPOSE 3000
CMD ["npm", "run", "start"]
