"""Offline calibration harness (additive, non-destructive).

Evaluates whether the Phase 2 regime layer and Phase 3 matrix scores — whose
weights/thresholds are Double-derived heuristics (NOT calibrated for
range-finder's pairs) — carry predictive signal on range-finder's own pairs.

This package is OFFLINE and READ-ONLY with respect to live behaviour:
    - it does NOT wire into refresh_data
    - it does NOT modify config.py / regime.py / matrix.py / app.py
    - it proposes tuned values in a markdown report; it never applies them

Entry point:  python3 -m calibration.run

Modules:
    features  — PURE, network-free helpers (forward outcomes, separation
                metrics, no-lookahead feature reconstruction). Fully unit-tested.
    run       — thin IO shell (fetch + disk cache + walk + markdown emit).
"""
