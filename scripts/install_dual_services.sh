#!/usr/bin/env bash
set -e
chmod +x scripts/start_alpaca.sh scripts/start_ibkr.sh
sudo cp systemd/tradebot-alpaca.service /etc/systemd/system/tradebot-alpaca.service
sudo cp systemd/tradebot-ibkr.service /etc/systemd/system/tradebot-ibkr.service
sudo systemctl daemon-reload
echo "Installed. Start with:"
echo "sudo systemctl start tradebot-alpaca"
echo "sudo systemctl start tradebot-ibkr"
