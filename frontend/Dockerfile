# syntax=docker/dockerfile:1

# ── Dependencies ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── Dev server (used by deploy/docker-compose.dev.yml via `target: dev`) ─────
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# ── Build ─────────────────────────────────────────────────────────────────────
FROM deps AS build
COPY . .
RUN npm run build

# ── Production: static files served by nginx ─────────────────────────────────
# Listens on 5173 so deploy/nginx/nginx.conf's `frontend:5173` upstream works
# in both dev and production.
FROM nginx:1.27-alpine AS prod
# Rendered to /etc/nginx/conf.d/default.conf at startup (envsubst)
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
