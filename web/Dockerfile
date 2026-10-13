# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
# Take the distribution's security fixes that landed after the base image was built: the scan in CI fails on fixable
# HIGH findings.
USER root
RUN apk upgrade --no-cache
USER nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY spr-headers.conf spr-proxy.conf /etc/nginx/
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
