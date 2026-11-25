import io
import json
from zipfile import ZipFile
from backend.v20_tech_swing_restore_artifacts import restore_latest


def test_restore_previous_snapshot(monkeypatch, tmp_path):
    snapshot={"schemaVersion":1,"researchOnly":True,"ordersSubmitted":0,
              "buyEnabled":False,"lastCompletedCommonBar":"2026-11-17",
              "preview":{"topCandidate":"AAPL"}}
    archive=io.BytesIO()
    with ZipFile(archive,"w") as z:
        z.writestr("candidate-2026-11-17.json",json.dumps(snapshot))
        z.writestr("swing-forward-report.json","{}")
    listing={"artifacts":[{"name":"swing-forward-candidate-snapshot",
             "expired":False,"created_at":"2026-11-18T00:00:00Z",
             "archive_download_url":"https://api.github.com/archive",
             "id":123,"workflow_run":{"id":111}}]}
    class Response:
        def __init__(self, body): self.body=body
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return self.body
    def fake_urlopen(req,timeout):
        return Response(json.dumps(listing).encode() if "artifacts?" in req.full_url else archive.getvalue())
    class FakeOpener:
        def open(self, req, timeout): return fake_urlopen(req, timeout)
    monkeypatch.setattr("backend.v20_tech_swing_restore_artifacts.build_opener", lambda *args: FakeOpener())
    r=restore_latest("owner/repo","token",tmp_path,current_run_id=222)
    assert r["restored"]==1
    assert (tmp_path/"candidate-2026-11-17.json").exists()
    assert not (tmp_path/"swing-forward-report.json").exists()
