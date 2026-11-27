FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY index.html build-config.cjs ./
COPY css ./css
COPY js ./js
ARG VITE_API_BASE_URL
ARG VITE_ENTRA_TENANT_ID
ARG VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_API_SCOPE
RUN node build-config.cjs

FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/index.html /usr/share/nginx/html/index.html
COPY --from=build /app/css/ /usr/share/nginx/html/css/
COPY --from=build /app/js/ /usr/share/nginx/html/js/
EXPOSE 8080
