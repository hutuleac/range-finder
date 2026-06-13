# Range Finder — Improvement Plan (informed by Double-main)

**Status:** Draft for review. No code written yet.
**Scope:** Light decision support — richer indicators, per-direction matrix scoring, regime detection. Stays a read-only dashboard. No order execution, no kill switches, no lifecycle orchestration.
**Source studied:** `/Users/peter/Projects/Double-main` (orchestration platform, 60+ indicators, ER×Hurst regime layer, indicator×bot-type profitability matrix).

---

## Executive summary

Double-main's analytical edge over range-finder is concentrated in three things range-finder lacks: a **regime layer** (Efficiency Ratio × Hurst, cross-validated, plus a COIL→EXPANSION→TREND→EXHAUSTION→NEUTRAL state machine), a **multi-timeframe data spine** (daily/weekly closes), and a **matrix scoring methodology** (each indicator weighted per strategy, normalized bot-type-aware, summed to a per-direction score) instead of one blended number.

The plan sequences by **data dependency, not by topic**: regime indicators need daily/weekly closes that range-finder doesn't fetch today, and the matrix consumes the regime outputs — so the order is forced. Everything here fits the existing Streamlit Cloud refresh-on-page-load model; no host migration is required.

One honesty caveat carried throughout: Double's weights (1–16) and FSM thresholds are **calibrated to Double's 15-symbol universe**. Ported into range-finder they are *heuristic starting points*, not validated constants. The plan labels them as such and ships them behind config so they can be tuned later.

---

## Three key findings

1. **The data spine is the real blocker.** Range-finder fetches only 4H klines (+ 4h OI/funding). Hurst (90 daily bars), Efficiency Ratio (10 daily), Hurst-weekly (~52 weekly), and regime confirmation all run on *daily/weekly* closes. Nothing in the regime or matrix work functions until daily/weekly fetching exists. This is Phase 1 and it gates the rest.

2. **Range-finder already has two scores; the matrix would be a third.** `calc_grid_score` (lagging, 0–10) and `calc_setup_score` (leading, 0–10) already coexist. Adding Double's matrix naively produces three overlapping numbers on one card. The matrix should *replace* the single blended grid score with a small per-direction matrix (grid-neutral / long-bias / short-bias + a directional column that feeds the existing Spot Trade Setup), while the Setup Score stays as the separate leading/predictive lens.

3. **The validated regime pair is ER × Hurst — lead with it, skip the redundant extras.** Double's `calc_regime_confirmation` specifically cross-checks Efficiency Ratio against Hurst. DFA and Hurst both measure persistence; porting both is redundant for "light decision support." Supertrend is a nice-to-have trend filter, not core. Core regime layer = ER + Hurst + regime_confirmation + the FSM.

---

## Recommendations (prioritized, phased)

### Phase 1 — Multi-timeframe data spine *(foundation; everything stacks on this)*
**Why first:** hard dependency for all regime indicators and the regime inputs the matrix reads.
**Work:**
- Extend `data_fetcher.fetch_klines` usage to also pull `"1d"` (~120 bars) and `"1w"` (~60 bars) per symbol. Same CCXT path, just more requests on the existing refresh — Streamlit Cloud compatible.
- Cache daily/weekly in the `MetricsCache` payload alongside the existing 4H metrics (`refresh_data.refresh_one`).
- Add a small fetch-failure fallback: if daily is unavailable, regime indicators return `UNKNOWN` rather than crashing the card (Double's pattern).
**Deliverable:** daily/weekly closes available in the cached payload for every pair.
**Effort:** S–M. **Risk:** low (additive).

### Phase 2 — Regime layer *(the highest-value analytical lift)*
**Why second:** depends on Phase 1; produces the regime inputs Phase 3 consumes.
**Port from `Double-main/core/indicators.py` + `core/regime_fsm.py`:**
- `calc_efficiency_ratio(df_daily, period=10)` → ER value + regime (TRENDING/TRANSITIONAL/RANGING) with grid/dir hints.
- `hurst_daily(closes, window=90)` + `_classify_hurst` → TRENDING / RANDOM / MEAN_REVERTING.
- `calc_regime_confirmation(er, hurst, trend_daily)` → combined regime + conviction (HIGH/…) + strategy hint. This is the keystone — it turns two raw numbers into one direction-aware verdict.
- Add `calc_adx_slope` (range-finder has ADX but not its slope) — FALLING/PEAKED/RISING/FLAT — used by the matrix's ADX normalization and (later) the FSM.

**FSM reclassified (discovered during Phase 2):** `regime_fsm.classify` is *not* a clean port for range-finder. It needs fields range-finder lacks (1H ADX, `swing_phase`, `compression_ratio`, 4H BB-band break) and Double's own docstring calls it provisional/uncalibrated. Building it here means substituting 5 inputs (squeeze→compression, 4H→1H ADX, structure→swing) and inventing thresholds — a new heuristic, not a port, with no ground truth to parity-test. **Deferred to Phase 2.5** as a clearly-labeled range-finder-native classifier, build-or-skip TBD. The headline regime badge does not need it: ER × Hurst × regime_confirmation already delivers the "RANGING · conviction HIGH → grid-favourable" verdict.
- `hurst_weekly` skipped — `regime_confirmation` only consumes daily Hurst.
**UI:** one regime badge per card (e.g. "NEUTRAL · ER 0.31 RANGING · Hurst 0.42 MEAN-REV · conviction HIGH → grid-favourable"). Surface in Range Finder cards and the cross-reference table.
**Labeling:** ship ER/Hurst/FSM thresholds in `config.py` (`REGIME` block) and comment them as *Double-derived heuristics, not calibrated for range-finder pairs*.
**Optional extras (defer):** DFA (redundant with Hurst), Supertrend (extra trend filter).
**Effort:** M. **Risk:** low–medium (numerical parity — see cross-cutting note).

### Phase 3 — Reduced profitability matrix *(DONE — shipped as additive view)*
**Status (build):** Shipped on branch `phase3-profitability-matrix` as an **additive view** (user decision): `matrix.py` scores 4 strategies (GRID_NEUTRAL/LONG/SHORT + DIRECTIONAL) from 13 range-finder indicators + the regime layer, cached as `payload["matrix"]`, surfaced as a strategy panel on each card with the winner highlighted + top contributors. Weights in `config.py["MATRIX"]` (heuristic). The existing `calc_grid_score` and the recommendation pipeline (direction/range/viability) are **untouched** — the headline-score swap is deferred to a follow-up once the matrix proves out, so the dashboard shows the matrix beside the existing score rather than replacing it.

Original plan (headline-replace approach) below, kept for reference:


**Why third:** consumes Phase 2's regime outputs (ER, Hurst, regime, ADX_slope are matrix inputs).
**Port the *methodology*, not Double's 7-bot matrix:**
- New `matrix.py`: an `IndicatorWeight(name, weights_by_strategy, category)` table and a `_normalize_indicator` with bot-type-aware 0–1 mapping (Double's `matrix_profitability_v1.2.py` is the template).
- **Reduced strategy columns** suited to range-finder's spot-grid + spot-trade focus: `GRID_NEUTRAL`, `GRID_LONG_BIAS`, `GRID_SHORT_BIAS`, `DIRECTIONAL` (the last feeds the existing tightened Spot Trade Setup).
- Score per column = Σ(weight × norm) / Σweight × 100, with a per-indicator breakdown (Double already returns this — reuse for the score-breakdown UI).
- **Resolve score relationship explicitly:** matrix `GRID_NEUTRAL` score *replaces* today's `calc_grid_score` blended output; the per-card breakdown replaces the current ad-hoc score pills. The Setup Score (leading) stays separate and unchanged.
**UI:** small matrix on each card (4 columns × score), highlight the winning strategy; keep the breakdown expander.
**Labeling:** weights in `config.py`, commented as heuristic starting points pending tuning.
**Effort:** M–L. **Risk:** medium (this is the biggest behavioral change — the headline number on every card moves).

### Phase 4 (optional) — Engineering-practice hardening *(borrow Double's discipline)*
- Per-subsystem try/except in `refresh_one` so one indicator failing doesn't blank a whole card (Double's scheduler lesson: a mid-run exception silently skips downstream work).
- Parity test fixtures (see cross-cutting note) promoted into the existing pytest suite.
**Effort:** S. **Risk:** low.

---

## Cross-cutting (applies to every phase)

- **Parity check per ported indicator.** CLAUDE.md requires math parity with the source. For each ported function, run one symbol (e.g. BTC) through both Double's snapshot and range-finder and diff the value. One assertion per indicator in `tests/` — cheap insurance against silent numerical drift.
- **Borrowed ≠ calibrated.** Every ported threshold/weight goes into `config.py` and is commented as a Double-derived heuristic, not validated for range-finder's universe. Backtest calibration is explicitly out of scope (per your direction); this keeps the door open to do it later without code surgery.
- **Deploy stays put.** All four phases run in-process on the existing refresh-on-page-load path. No daemon, no persistent disk, no host move. Reserve the "flexible deploy" option for a future calibration job, which is out of this scope.

---

## Explicitly out of scope (from Double, deliberately not ported)
Orchestrator tick / SCAN-MANAGE-DEPLOY, kill switches, executor & Pionex writes, bot lifecycle FSM, Kelly v2 sizing, approval queue, Telegram-on-criticality daemon, backtest calibration sweeps. These belong to Double's "platform" identity; range-finder stays a sharp read-only dashboard.

## Suggested order of execution
Phase 1 → Phase 2 → Phase 3 → Phase 4. Phases 1–2 are low-risk and independently shippable. Phase 3 is the one to review carefully before merging because it changes the headline score on every card.
