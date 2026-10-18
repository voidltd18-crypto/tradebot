"""Isolated bounded RSS soak: no network, broker credentials, or trading imports."""
import ast
import gc
import os
import resource
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
names = {"_v19_process_rss_mb", "_release_transient_memory"}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(nodes) == 2
namespace = {"Optional": __import__("typing").Optional, "gc": gc}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec"), namespace)
rss = namespace["_v19_process_rss_mb"]
trim = namespace["_release_transient_memory"]
assert rss() is not None, "Linux /proc RSS unavailable"
# Simulate repeated bounded allocations and memory trim without loading the bot.
samples = []
for cycle in range(80):
    payload = [bytearray(1024 * 1024) for _ in range(16)]
    for i, chunk in enumerate(payload):
        chunk[0] = i
    del payload
    trim("")
    samples.append(rss())
peak = max(samples)
tail = samples[-20:]
growth = max(0, sum(tail)/len(tail) - sum(samples[:20])/20)
print(f"V19 RSS SOAK | cycles=80 peak_mb={peak:.2f} last_mb={samples[-1]:.2f} tail_growth_mb={growth:.2f}")
assert peak < 180, f"isolated memory soak exceeded 180 MiB: {peak}"
assert growth < 40, f"memory remained elevated across cycles: {growth}"
