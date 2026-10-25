from backend.v19_crypto_profit_sell_executor import _record_worker_status, profit_sell_status

def test_worker_status(tmp_path):
    path = str(tmp_path / 'worker.sqlite')
    assert profit_sell_status(path)['lastPoll'] is None
    _record_worker_status(path, status='completed', detail='no eligible exit', checked=2)
    status = profit_sell_status(path)
    assert status['lastPoll']['status'] == 'completed'
    assert status['lastPoll']['checked'] == 2
