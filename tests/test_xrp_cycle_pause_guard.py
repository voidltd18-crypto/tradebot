from backend.v19_xrp_cycle_executor import cycle_once


class NeverCall:
    def __getattr__(self, key):
        raise AssertionError("broker should not be accessed when paused")


def test_pause_never_calls_broker(tmp_path):
    assert cycle_once(NeverCall(), NeverCall(), str(tmp_path/"test.db"),
                      configured_spend="ALL",enabled=True,
                      trading_allowed=False)["orderSubmitted"] is False
