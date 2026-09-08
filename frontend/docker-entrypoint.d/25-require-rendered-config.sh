#!/bin/sh
set -eu

: "${API_UPSTREAM:?API_UPSTREAM must name the backend service}"
: "${SERVER_NAME:?SERVER_NAME must name the browser hostname}"
if [ ! -s /etc/nginx/conf.d/default.conf ]; then
    echo "FATAL: nginx configuration was not rendered." >&2
    exit 1
fi
nginx -t