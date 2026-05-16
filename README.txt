Render Button Logging Patch

Replace:
backend/main.py

Added instant logs for:
- money-buy
- sell-worst
- weekly-refresh
- refresh-universe

You will now immediately see:
BUTTON HIT: ...

in Render logs as soon as the button request reaches backend.
