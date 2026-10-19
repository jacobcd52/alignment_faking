#!/bin/bash
# DigitalOcean user-data for the chat app. provision.py fills in __TINKER_KEY__, __PASSWORD__, __ADMIN_TOKEN__ and
# __ADMIN_PY_B64__. The app code arrives afterwards through /admin/deploy.
exec > /var/log/glmchat-setup.log 2>&1
set -eux
export DEBIAN_FRONTEND=noninteractive
IP=$(curl -s http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address)
HOST="$(echo "$IP" | tr . -).sslip.io"

mkdir -p /etc/glmchat /opt/glmchat
echo "TINKER_API_KEY=__TINKER_KEY__" > /etc/glmchat/env
echo "__ADMIN_TOKEN__" > /etc/glmchat/admin_token
chmod 600 /etc/glmchat/env /etc/glmchat/admin_token
echo "__ADMIN_PY_B64__" | base64 -d > /opt/glmchat/admin.py

# swap, so tokenizer loading plus a few containers never OOM
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

apt-get update
apt-get install -y docker.io python3-venv python3-pip git curl gpg debian-keyring debian-archive-keyring apt-transport-https ufw
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

cat > /etc/systemd/system/glmchat-admin.service <<'UNIT'
[Unit]
Description=Chat app admin endpoint
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/glmchat/admin.py
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now glmchat-admin

HASH=$(caddy hash-password --plaintext '__PASSWORD__')
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    handle /admin/* {
        reverse_proxy 127.0.0.1:9100
    }
    handle {
        basic_auth {
            glm $HASH
        }
        reverse_proxy 127.0.0.1:8765
    }
}
CADDY
systemctl restart caddy
ufw allow 22
ufw allow 80
ufw allow 443
ufw --force enable

python3 -m venv /opt/glmchat/venv
/opt/glmchat/venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
/opt/glmchat/venv/bin/pip install -q "fastapi>=0.110" "uvicorn>=0.29" "tinker>=0.23" \
    "transformers>=4.57.6,<=5.5.4,!=5.4.*,!=5.5.0,!=5.5.1,!=5.5.2,!=5.5.3" "tiktoken>=0.12" "pillow>=10" "numpy>=1.24" \
    "huggingface-hub>=0.20" "pydantic>=2" httpx
/opt/glmchat/venv/bin/pip install -q --no-deps tinker-cookbook
docker pull python:3.12

cat > /etc/systemd/system/glmchat.service <<UNIT
[Unit]
Description=Chat app
After=network.target docker.service
[Service]
EnvironmentFile=/etc/glmchat/env
WorkingDirectory=/opt/glmchat
ExecStart=/opt/glmchat/venv/bin/python /opt/glmchat/chat_app/server.py --host 127.0.0.1 --port 8765 --allowed-host $HOST
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable glmchat
if [ -f /opt/glmchat/chat_app/server.py ]; then systemctl restart glmchat; fi
echo SETUP_DONE
