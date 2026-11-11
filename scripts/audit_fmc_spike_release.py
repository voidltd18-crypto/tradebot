"""One-command, deliberately fail-closed FMC Spike Mode release evidence audit.

Runs local CSV costed replay and optional GET-ONLY Alpaca PAPER account
inspection. NEVER submits, replaces or cancels broker orders. Not connected
to the live stock engine and cannot approve a production rollout.
"""
import argparse
import json
import os

from backend.stock_momentum_cost_model import CostAssumptions
from backend.stock_paper_account_reader import PaperAccountReader
from scripts.replay_fmc_csv import run_csv_replay


def release_audit(csv_path, *, source, entry_price, paper_reader=None,
                  assumptions=None):
    """Assess evidence presence, without ever treating labels as proof.

    Caller-provided source labels and CSV contents cannot constitute
    independent market-data provenance. A paper account read is not a paper
    execution test. Therefore 'releaseReady' always stays False.
    """
    replay = run_csv_replay(
        csv_path, symbol="FMC", source=source, entry_price=entry_price
    )
    # run_csv_replay currently uses its default conservative fill costs.
    # Alternate modeled assumptions should be applied to the same bars.
    if assumptions is not None:
        from scripts.replay_fmc_csv import load_bars_csv
        from backend.stock_momentum_cost_model import compare_costed_exits
        replay.update(compare_costed_exits(
            entry_price, load_bars_csv(csv_path), assumptions=assumptions
        ))
    paper = {"checked": False, "accountReadOnly": True}
    if paper_reader is not None:
        account = paper_reader.confirm_paper_account()
        paper = {
            "checked": True,
            "accountReadOnly": True,
            "paperOnly": account["paperOnly"],
            "accountIdPresent": account["accountIdPresent"],
            "accountStatus": account["accountStatus"],
        }
        # Never require an FMC paper position for the read-only check:
        # no position is a valid account outcome, not a reason to buy FMC.
    return {
        "symbol": "FMC",
        "readOnly": True,
        "ordersSubmitted": 0,
        "releaseReady": False,
        "evidence": {
            "marketDataLabel": source,
            "independentlyVerifiedHistoricalQuotes": False,
            "paperAccountRead": paper,
            "actualPaperSellFillVerified": False,
            "productionBrokerGateIntegrationVerified": False,
            "persistentDeployedStorageVerified": False,
        },
        "candidateExitSimulation": replay["candidate"],
        "referenceExitSimulation": replay["referenceTrailingExit"],
        "simulatedPnlDifferenceUsd": replay["candidateMinusReferenceNetPnlUsd"],
        "blockingReasons": [
            "Unverified historical FMC data provenance and feed coverage",
            "No actual Alpaca paper sell fill / partial fill evidence",
            "No production strategy gate and restart-safe durable storage verification",
            "No multi-session out-of-sample profitability evidence",
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="FMC historical/cost/paper READ-ONLY release audit"
    )
    parser.add_argument("csv_file")
    parser.add_argument("--source", required=True)
    parser.add_argument("--entry-price", type=float, required=True)
    parser.add_argument("--paper-read-only", action="store_true")
    parser.add_argument("--spread-bps", type=float, default=20)
    parser.add_argument("--slippage-bps", type=float, default=15)
    args = parser.parse_args()
    paper = None
    if args.paper_read_only:
        # Explicit PAPER names prevent accidental implicit use of live keys.
        key = os.environ.get("ALPACA_PAPER_API_KEY_ID", "")
        secret = os.environ.get("ALPACA_PAPER_API_SECRET_KEY", "")
        paper = PaperAccountReader(api_key=key, api_secret=secret)
    report = release_audit(
        args.csv_file, source=args.source, entry_price=args.entry_price,
        paper_reader=paper,
        assumptions=CostAssumptions(
            spread_bps=args.spread_bps,
            exit_slippage_bps=args.slippage_bps,
        ),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
