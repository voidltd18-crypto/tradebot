"""V18.3.78 Crypto Live Profit Mode.

Turns the existing Alpaca crypto executor back on for NEW live exposure while
keeping the existing broker/account checks, stop/trailing exits, cooldowns,
loss brakes, performance quarantine and Piggy/stock-capital isolation.

This does not remove protective exits or the live evidence gate. It changes the
Governor from a hard shadow-only kill switch into advisory research telemetry.

Live-entry scope:
- real Alpaca crypto account only (never PAPER)
- global bot pause/manual override/emergency stop still block entries
- existing crypto risk block still applies
- existing live evidence gate still applies
- existing 5s protective exit loop remains untouched
- crypto max positions capped at 4
- adaptive liquidity percentile widened from 50% to 25%, while the existing
  hard minimum liquidity floor remains enforced
"""

from __future__ import annotations

VERSION = "V18.3.78"


def install_v18378_crypto_live_profit_mode(app, m) -> None:
    original_permission = m._v18334_crypto_live_entry_permission
    original_bridge_payload = m.v18234_crypto_bridge_payload

    # Keep the user's established four-position crypto preference and broaden
    # the adaptive liquidity pool without removing the hard $250 minimum.
    m.V18234_CRYPTO_LIVE_MAX_POSITIONS = min(
        4, max(1, int(getattr(m, "V18234_CRYPTO_LIVE_MAX_POSITIONS", 4) or 4))
    )
    m.V18253_CRYPTO_LIQUIDITY_PERCENTILE = min(
        0.25, float(getattr(m, "V18253_CRYPTO_LIQUIDITY_PERCENTILE", 0.50) or 0.50)
    )

    def live_profit_permission():
        prior = {}
        try:
            prior = dict(original_permission() or {})
        except Exception:
            prior = {}

        enabled = bool(getattr(m, "V18234_CRYPTO_LIVE_ENABLED", False))
        paper = bool(getattr(m, "PAPER", True))
        bot_enabled = bool(getattr(m, "bot_enabled", False))
        manual_override = bool(getattr(m, "manual_override", False))
        emergency_stop = bool(getattr(m, "emergency_stop", False))

        allowed = (
            enabled
            and not paper
            and bot_enabled
            and not manual_override
            and not emergency_stop
        )

        reason = (
            "V18.3.78 live profit mode: Governor research remains advisory; "
            "normal crypto evidence/risk/safety gates still control execution"
            if allowed
            else prior.get("reason") or "Live crypto entry prerequisites not satisfied"
        )
        return {
            **prior,
            "allowed": bool(allowed),
            "stage": "LIVE_PROFIT_MODE" if allowed else prior.get("stage", "BLOCKED"),
            "reason": reason,
            "profitMode": True,
            "researchAdvisoryOnly": True,
        }

    def governor_shadow_only():
        # V18.3.78: research continues, but it no longer blocks the live executor.
        # All subsequent risk/evidence/cooldown checks in the original cycle remain.
        return False

    def bridge_payload():
        payload = dict(original_bridge_payload() or {})
        permission = live_profit_permission()
        paused = (
            not bool(getattr(m, "bot_enabled", False))
            or bool(getattr(m, "manual_override", False))
            or bool(getattr(m, "emergency_stop", False))
        )
        payload["version"] = VERSION
        payload["governorEntryPermission"] = permission
        payload["liveEntriesEnabled"] = bool(permission.get("allowed"))
        payload["shadowOnly"] = False
        payload["shadowOnlyReason"] = None
        payload["newEntriesPaused"] = bool(paused)
        payload["pauseReason"] = (
            "BOT_PAUSED" if not bool(getattr(m, "bot_enabled", False))
            else "MANUAL_OVERRIDE" if bool(getattr(m, "manual_override", False))
            else "EMERGENCY_STOP" if bool(getattr(m, "emergency_stop", False))
            else None
        )
        payload["liveMaxPositions"] = int(m.V18234_CRYPTO_LIVE_MAX_POSITIONS)
        payload["cryptoLiveProfitMode"] = True
        payload["researchAdvisoryOnly"] = True
        payload["liquidityPercentile"] = float(m.V18253_CRYPTO_LIQUIDITY_PERCENTILE)
        return payload

    m._v18334_crypto_live_entry_permission = live_profit_permission
    m._v18289_governor_shadow_only = governor_shadow_only
    m.v18234_crypto_bridge_payload = bridge_payload

    print(
        f"{VERSION} CRYPTO LIVE PROFIT MODE | installed "
        f"paper={bool(getattr(m, 'PAPER', True))} "
        f"live_enabled={bool(getattr(m, 'V18234_CRYPTO_LIVE_ENABLED', False))} "
        f"max_positions={m.V18234_CRYPTO_LIVE_MAX_POSITIONS} "
        f"liquidity_percentile={m.V18253_CRYPTO_LIQUIDITY_PERCENTILE:.2f} "
        "governor=ADVISORY risk_gates=UNCHANGED evidence_gate=UNCHANGED "
        "protective_exits=UNCHANGED",
        flush=True,
    )
