# TradeBot V14 Autonomous AI Scientist

V14 adds an automatic, research-only scientific layer on top of V13 Memory.

## Endpoints

- `GET /v14/scientist/status`
- `GET /v14/scientist/hypotheses`
- `GET /v14/scientist/experiments`
- `GET /v14/scientist/events`
- `GET /v14/scientist/constitution`

## Behaviour

- Generates hypotheses only from persisted V13 evidence.
- Designs shadow-only A/B research experiments.
- Imports existing V7 research brains as observational validation evidence.
- Does not place orders, alter live settings, or bypass CEO/Board/operator safeguards.
- Runs automatically every 30 minutes by default.

Optional environment variables:

- `V14_SCIENTIST_ENABLED=true`
- `V14_SCIENTIST_INTERVAL_SECONDS=1800`
- `V14_SCIENTIST_STARTUP_DELAY_SECONDS=55`
- `V14_MIN_MEMORY_CONFIDENCE=55`
- `V14_MIN_RESEARCH_SAMPLES=100`
