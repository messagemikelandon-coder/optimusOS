#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Installing Docker and Compose plugin..."
  sudo apt update
  sudo apt install -y docker.io docker-compose-plugin
fi

sudo systemctl enable --now docker

if grep -q '127.0.0.1:8000:8000' docker-compose.yml; then
  echo "Opening Optimus to the private network on port 8000..."
  sed -i 's/127.0.0.1:8000:8000/8000:8000/' docker-compose.yml
fi

sudo docker compose up -d --build

ip_addr="$(hostname -I | awk '{print $1}')"
echo
echo "Optimus is running."
echo "Open this from another device on the same private network or VPN:"
echo "http://${ip_addr}:8000"
