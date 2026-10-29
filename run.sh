#!/usr/bin/env bash
# Dipakai PM2 di VPS: muat .env (TYPESAFE_API_KEY, NETIZEN_PASS, PORT) lalu jalankan server web.
cd "$(dirname "$0")"; set -a; . ./.env; set +a
exec .venv/bin/python spike/server.py
