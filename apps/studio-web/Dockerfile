# --- build stage ---
FROM node:20-slim AS build
WORKDIR /app
COPY apps/studio-web/package.json ./package.json
RUN npm install
COPY apps/studio-web .
RUN npm run build

# --- dev stage ---
FROM node:20-slim AS dev
WORKDIR /app
COPY apps/studio-web/package.json ./package.json
RUN npm install
COPY apps/studio-web .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# --- runtime stage ---
FROM nginx:alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
