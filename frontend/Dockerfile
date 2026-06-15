# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# Serve stage — lightweight static server
FROM node:20-alpine AS serve
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
# Security headers (CSP etc.) for the static serve — see serve.json rationale.
COPY serve.json ./dist/serve.json
EXPOSE 5173
CMD ["serve", "-s", "dist", "-l", "5173"]
