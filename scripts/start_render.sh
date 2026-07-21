#!/bin/sh
set -eu

backend_pid=""
nginx_pid=""

cleanup() {
    if [ -n "${backend_pid}" ]; then
        kill -TERM "${backend_pid}" 2>/dev/null || true
    fi
    if [ -n "${nginx_pid}" ]; then
        kill -TERM "${nginx_pid}" 2>/dev/null || true
    fi
    wait "${backend_pid}" 2>/dev/null || true
    wait "${nginx_pid}" 2>/dev/null || true
}

trap cleanup INT TERM

mkdir -p /var/lib/nginx/body /var/lib/nginx/proxy /var/lib/nginx/fastcgi /var/lib/nginx/uwsgi /var/lib/nginx/scgi

envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
nginx -t

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

while kill -0 "${backend_pid}" 2>/dev/null && kill -0 "${nginx_pid}" 2>/dev/null; do
    sleep 1
done

backend_status=0
nginx_status=0

wait "${backend_pid}" || backend_status=$?
wait "${nginx_pid}" || nginx_status=$?

cleanup

if [ "${backend_status}" -ne 0 ]; then
    exit "${backend_status}"
fi

exit "${nginx_status}"
