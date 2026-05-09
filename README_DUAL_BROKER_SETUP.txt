TradeBot Dual Broker Setup

This lets your tablet run BOTH bots at the same time:

Alpaca bot:
http://TABLET-IP:8000/status

IBKR bot:
http://TABLET-IP:8001/status
http://TABLET-IP:8001/broker-status

Install:

1. Copy env files:
cp env/alpaca.env.example env/alpaca.env
cp env/ibkr.env.example env/ibkr.env

2. Edit keys:
nano env/alpaca.env
nano env/ibkr.env

3. Install requirements:
source .venv/bin/activate
pip install -r backend/requirements.txt
pip install ib_insync nest_asyncio

4. Start manually:
bash scripts/start_alpaca.sh

Open a second terminal:
bash scripts/start_ibkr.sh

5. Test:
http://TABLET-IP:8000/status
http://TABLET-IP:8001/broker-status

Keep IBKR BOT_ENABLED=false at first until broker-status is connected.
