# --- build stage ---
FROM node:20-slim AS build
WORKDIR /app
COPY apps/studio-web/package.json apps/studio-web/package-lock.json ./
RUN npm ci
COPY apps/studio-web .
RUN npm run build

# --- dev stage ---
FROM node:20-slim AS dev
RUN groupadd --gid 1000 appuser || true && useradd --uid 1000 --gid 1000 --create-home appuser || true
WORKDIR /app
COPY apps/studio-web/package.json apps/studio-web/package-lock.json ./
RUN npm ci
COPY --chown=appuser:appuser apps/studio-web .
USER appuser
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# --- runtime stage ---
FROM nginxinc/nginx-unprivileged:alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
