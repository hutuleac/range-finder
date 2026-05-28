# tests/fixtures/capture_snapshot.py
"""Run once to dump live pyonex.db → metrics_snapshot.json."""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from trade_logger import all_latest

rows = all_latest()
if not rows:
    print("ERROR: DB is empty. Run the app or `python3 -m refresh_data` first.")
    sys.exit(1)

snapshot = [
    {"symbol": r.symbol, "price": r.price, "score": r.score,
     "direction": r.direction, "payload": r.payload}
    for r in rows
]
out = os.path.join(os.path.dirname(__file__), "metrics_snapshot.json")
with open(out, "w") as f:
    json.dump(snapshot, f, indent=2, default=str)
print(f"Captured {len(snapshot)} rows → {out}")
for r in snapshot:
    print(f"  {r['symbol']:15s}  score={r['score']:.1f}")
