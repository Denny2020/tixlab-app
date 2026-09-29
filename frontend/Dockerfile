# syntax=docker/dockerfile:1
# nginx-unprivileged runs as UID 101 and listens on 8080, no root needed.
FROM nginxinc/nginx-unprivileged:1.30.5-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public/ /usr/share/nginx/html/
EXPOSE 8080
