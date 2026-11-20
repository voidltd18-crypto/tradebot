from datetime import date, timedelta
import pytest
from backend.tradebot_v2.historical_csv import parse_adjusted_close_csv, evaluate_csv


def fixture(n=90):
    return "date,adjusted_close\n" + "".join(
        f"{date(2025,1,1)+timedelta(days=i)},{100+i/10}\n"
        for i in range(n)
    )


def test_strict_csv_parses_sorted_adjusted_prices():
    result = parse_adjusted_close_csv(fixture())
    assert len(result) == 90 and result[0].close == 100


def test_csv_backtest_keeps_provenance():
    result = evaluate_csv("MSFT", fixture(), source="synthetic fixture only",
                          training_end=date(2025,2,15))
    assert result.source == "synthetic fixture only"
    assert result.test_signals == 0


@pytest.mark.parametrize("bad", [
    "", "date,close\n2025-01-01,100\n",
    "date,adjusted_close\n2025-01-01,nan\n",
    "date,adjusted_close\n2025-01-01,-2\n",
    "date,adjusted_close\n2025-01-01,100\n2025-01-01,101\n",
    "date,adjusted_close\n2025-01-02,100\n2025-01-01,101\n",
    "date,adjusted_close\nnot-a-date,100\n",
])
def test_csv_rejects_bad_data(bad):
    with pytest.raises(ValueError):
        parse_adjusted_close_csv(bad)
