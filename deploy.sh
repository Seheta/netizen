#!/usr/bin/env bash
# Kirim kode ke VPS dan restart server web. Jalankan dari folder netizen: bash deploy.sh
# Kode -> /root/netizen (PM2 "netizen", 127.0.0.1:8798); halaman -> /var/www/moddestlab/netizen (moddestlab.com/netizen/).
# .env di server tidak ikut dikirim; isi sekali dengan scp .env root@31.97.66.253:/root/netizen/.env
set -euo pipefail
cd "$(dirname "$0")"
HOST=root@31.97.66.253
tar czf - --exclude='spike/results' --exclude='__pycache__' spike data web run.sh \
  | ssh "$HOST" "mkdir -p /root/netizen /var/www/moddestlab/netizen && tar xzf - --no-same-owner -C /root/netizen \
    && cp /root/netizen/web/index.html /var/www/moddestlab/netizen/index.html \
    && cd /root/netizen && [ -d .venv ] || python3 -m venv .venv \
    && .venv/bin/pip install -q 'typesafe-sdk>=0.7.5' \
    && (pm2 restart netizen >/dev/null 2>&1 || pm2 start run.sh --name netizen --interpreter bash) && pm2 save >/dev/null"
echo "deployed -> https://moddestlab.com/netizen/"
