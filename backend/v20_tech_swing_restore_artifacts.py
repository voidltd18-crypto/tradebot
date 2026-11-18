"""Restore latest archived research snapshots from prior GitHub Actions artifact.

No writes to GitHub, broker access, or live orders. GitHub artifact retention
limits durability; the archive must be exported externally for long-term records.
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from zipfile import ZipFile

ARTIFACT_NAME = "swing-forward-candidate-snapshot"


def restore_latest(repo, token, destination, *, current_run_id=None):
    if not repo or not token:
        raise ValueError("GitHub repository and token required")
    base = f"https://api.github.com/repos/{repo}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    class SafeRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            redirected = super().redirect_request(req, fp, code, msg, hdrs, newurl)
            if redirected is not None and urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
                redirected.remove_header("Authorization")
            return redirected

    opener = build_opener(SafeRedirect)
    def get(url):
        with opener.open(Request(url, headers=headers), timeout=30) as response:
            return response.read()
    artifacts = json.loads(get(f"{base}/actions/artifacts?per_page=100"))["artifacts"]
    candidates = [a for a in artifacts if a["name"] == ARTIFACT_NAME and not a["expired"]
                  and str(a.get("workflow_run", {}).get("id")) != str(current_run_id)]
    candidates.sort(key=lambda a: a["created_at"], reverse=True)
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    if not candidates:
        return {"restored": 0, "sourceArtifact": None}
    # Fetch only the latest aggregate artifact. Each run carries forward the
    # entire archive, rather than downloading many isolated previous runs.
    latest = candidates[0]
    data = get(latest["archive_download_url"])
    restored = 0
    with ZipFile(io.BytesIO(data)) as z:
        for member in z.infolist():
            filename = Path(member.filename).name
            if not filename.startswith("candidate-") or not filename.endswith(".json"):
                continue
            if member.file_size > 100000:
                raise ValueError("Unexpectedly large snapshot")
            payload = z.read(member)
            parsed = json.loads(payload)
            if parsed.get("researchOnly") is not True or parsed.get("ordersSubmitted") != 0:
                raise ValueError("Unsafe prior snapshot")
            target = dest / filename
            if target.exists() and target.read_bytes() != payload:
                raise ValueError(f"Conflicting archived snapshot: {filename}")
            target.write_bytes(payload)
            restored += 1
    return {"restored": restored, "sourceArtifact": latest["id"]}


if __name__ == "__main__":
    print(json.dumps(restore_latest(os.environ["GITHUB_REPOSITORY"],
                                    os.environ["GH_TOKEN"],
                                    os.environ.get("SNAPSHOT_DIR", "swing-forward-snapshots"),
                                    current_run_id=os.environ.get("GITHUB_RUN_ID"))))
