#!/usr/bin/env bash
# Oracle Cloud 무료 VM(Ubuntu 22.04)에 Stocking 설치.
# 사용: 레포를 ~/Stocking 에 clone 한 뒤  bash ~/Stocking/deploy/oracle_setup.sh
# 키는 이 스크립트에 넣지 않는다 → ~/Stocking/.env 를 직접 만든다 (스크립트가 안내).
set -euo pipefail

APP_DIR="$HOME/Stocking"
DATA_DIR="$HOME/stocking-data"
PORT=8800
IP=$(curl -s https://api.ipify.org)
DOMAIN="${IP//./-}.sslip.io"          # 도메인 없이 HTTPS: 1-2-3-4.sslip.io → 1.2.3.4

echo "== 공인 IP: $IP  (토스 허용 IP에 이걸 넣는다)"

# 1) 메모리 1GB VM 대비 스왑 2GB (pandas 설치·실행 여유)
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# 2) 패키지 + Caddy(HTTPS 자동 발급 리버스 프록시)
sudo apt-get update -y
sudo apt-get install -y git python3-venv python3-pip debian-keyring debian-archive-keyring apt-transport-https curl
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

# 3) Oracle 우분투 이미지는 OS 방화벽이 80/443 을 막아둔다 → 연다
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p tcp --dport $p -j ACCEPT
done
sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save

# 4) 파이썬 환경
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p "$DATA_DIR"

# 5) 서버(127.0.0.1 에만 열고 바깥은 Caddy 가 HTTPS 로 넘겨준다)
sudo tee /etc/systemd/system/stocking.service >/dev/null <<EOF
[Unit]
Description=Stocking
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=DATA_DIR=$DATA_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:$PORT {
        flush_interval -1
    }
}
EOF

sudo systemctl daemon-reload
sudo systemctl enable stocking caddy

if [ ! -f "$APP_DIR/.env" ]; then
  echo
  echo "== 아직 .env 가 없다. 아래로 만든 뒤:  sudo systemctl restart stocking caddy"
  echo "   nano $APP_DIR/.env   (APP_PASSWORD, TOSS_CLIENT_ID, TOSS_CLIENT_SECRET, FINNHUB_API_KEY, OPENAI_API_KEY, DEFAULT_WATCHLIST)"
  echo "   chmod 600 $APP_DIR/.env"
else
  chmod 600 "$APP_DIR/.env"
  sudo systemctl restart stocking caddy
fi
echo
echo "== 접속 주소: https://$DOMAIN"
echo "== 토스 허용 IP: $IP"
