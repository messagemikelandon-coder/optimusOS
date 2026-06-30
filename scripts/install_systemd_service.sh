#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=/etc/systemd/system/optimusos.service

sudo tee "$UNIT" >/dev/null <<UNIT
[Unit]
Description=OptimusOS local deployment
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$ROOT
ExecStart=$ROOT/scripts/optimusctl.sh start
ExecStop=$ROOT/scripts/optimusctl.sh stop
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable optimusos.service
echo "Installed and enabled optimusos.service"
