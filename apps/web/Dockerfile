# US-WATCHER web image (Next.js production server).
FROM node:20-alpine AS build
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
# Same-origin: the browser calls /api/* and Next proxies to API_PROXY_TARGET.
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
