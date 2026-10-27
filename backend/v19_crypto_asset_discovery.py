"""Read-only discovery of active tradable Alpaca USD crypto markets.

This does not submit orders, alter positions, or automatically approve purchases.
"""
def discover_tradable_usd_crypto(client):
    from alpaca.trading.requests import GetAssetsRequest
    from alpaca.trading.enums import AssetClass, AssetStatus
    assets = client.get_all_assets(GetAssetsRequest(
        asset_class=AssetClass.CRYPTO, status=AssetStatus.ACTIVE))
    if not isinstance(assets, list):
        raise ValueError("Broker asset inventory unavailable")
    found = set()
    for a in assets:
        symbol = str(getattr(a, "symbol", "") or "").upper().replace("/", "")
        if not (str(getattr(a, "asset_class", "")).lower().endswith("crypto")
                and str(getattr(a, "status", "")).lower().endswith("active")
                and getattr(a, "tradable", False) is True
                and symbol.endswith("USD")
                and symbol[:-3].isalpha() and 2 <= len(symbol[:-3]) <= 10):
            continue
        found.add(symbol)
    return sorted(found)
