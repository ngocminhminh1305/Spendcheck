# Spendcheck website. Stage 1 compiles the React app with Vite; stage 2 is a small nginx that
# serves the files and forwards /api to the gateway (nginx.conf), so the browser sees one origin.
# Build context is this folder:  docker build -t spendcheck/frontend frontend
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
