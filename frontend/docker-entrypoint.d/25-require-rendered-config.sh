#!/bin/sh
set -eu
rendered="${NGINX_ENVSUBST_OUTPUT_DIR:-/etc/nginx/conf.d}/default.conf"
if [ -z "${API_UPSTREAM:-}" ] || [ ! -s "$rendered" ]; then
    echo "$0: FATAL: API_UPSTREAM or rendered default.conf is missing; check env and conf.d permissions." >&2
    exit 1
fi
if grep -q '\${API_UPSTREAM}' "$rendered"; then
    echo "$0: FATAL: API_UPSTREAM was not substituted." >&2
    exit 1
fi
nginx -t
