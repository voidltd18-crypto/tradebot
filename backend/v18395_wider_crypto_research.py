"""V18.3.95 Wider Crypto Research.

Research/advisory-only expansion:
- Raises the Shadow Research target from 100 to 200 markets.
- Does not relax the autonomous live crypto execution gates.
- Does not submit orders.
"""

VERSION = "V18.3.95"


def install_v18395_wider_crypto_research(app, m) -> None:
    # Shadow/Kraken research only. The monolith explicitly keeps these external
    # markets out of the autonomous live execution cycle.
    previous = int(getattr(m, "V18307_SHADOW_RESEARCH_UNIVERSE_TARGET", 100) or 100)
    target = max(previous, 200)
    setattr(m, "V18307_SHADOW_RESEARCH_UNIVERSE_TARGET", target)

    print(
        f"{VERSION} WIDER CRYPTO RESEARCH | shadow_target={target} "
        f"previous={previous} advisory_only=True live_gate_changes=False orders=False",
        flush=True,
    )
