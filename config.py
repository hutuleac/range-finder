"""Pyonex config — Python port of config.js patched with Pyonex.txt overrides."""
from __future__ import annotations

CFG: dict = {
    "APP_VERSION": "6.4",
    "REFRESH_INTERVAL_SEC": 1200,

    # OI
    "OI_PERIOD": "4h",
    "OI_LIMIT": 42,

    # Klines
    "KLINES_MAIN": 210,
    "KLINES_FVG": 100,
    "KLINES_5D": 30,
    "KLINES_14D": 84,
    "KLINES_30D": 180,
    "FLOW_LIMIT": 24,

    # Indicators
    "RSI_PERIOD": 14,
    "ATR_PERIOD": 14,
    "EMA_FAST": 50,
    "EMA_SLOW": 200,
    "STRUCT_LOOKBACK_4H": 20,
    "STRUCT_LOOKBACK_30D": 40,
    "FVG_MAX_GAPS": 5,

    # Donchian (new vs JS — from Pyonex.txt)
    "DONCHIAN_PERIOD_SHORT": 20,
    "DONCHIAN_PERIOD_LONG": 55,
    "DONCHIAN_BREAK_BUFFER_PCT": 0.25,

    # Squeeze (new vs JS — from Pyonex.txt)
    "SQUEEZE": {"BB_WIDTH_MAX": 5.0, "DC_ATR_RATIO_MAX": 1.0},

    # Thresholds
    "RSI_OB": 70, "RSI_OS": 30,
    "RSI_EXTREME_OB": 75, "RSI_EXTREME_OS": 25,
    "FLOW_STRONG": 5.0, "FLOW_PARTIAL": 2.0,
    "OI_SQUEEZE_HIGH": 10.0, "OI_SQUEEZE_MED": 5.0,
    "POC_NEAR_PCT": 0.5,
    "FVG_NEAR_PCT": 1.0,
    "FVG_ENTRY_PCT": 2.0,
    "POC_CONFLUENCE_PCT": 1.0,
    "VOL_SPIKE_MULT": 2.0, "VOL_AVG_WINDOW": 20,
    "SCORE_BOT_MIN": 7.5,
    "CVD_LATERAL_RATIO": 0.2,
    "SL_ATR_MULT": 1.5,
    "TP1_ATR_MULT": 3.0,
    "TP2_ATR_MULT": 5.25,
    "TRAIL_OFFSET_MULT": 0.5,
    "GRID_BUFFER": 0.02,
}

GRID_CONFIG: dict = {
    "DEFAULT_CAPITAL": 300,
    "FEE_PCT": 0.001,
    "TARGET_NET_PCT": 0.008,
    "MIN_NET_PCT": 0.006,
    "ATR_MULTIPLIER_DEFAULT": 2.5,
    "GEOMETRIC_THRESHOLD_PCT": 20,
    "SL_BUFFERS": {"stable": 0.06, "moderate": 0.09, "volatile": 0.13},
    "TP_BUFFERS": {"stable": 0.04, "moderate": 0.05, "volatile": 0.07},
    "VIABILITY": {
        "ADX_IDEAL": 18,
        "ADX_BLOCK": 22,
        "RSI_BLOCK": 68,
        "BB_MIN": 2.0,
        "BEARISH_ADX_BLOCK": 18,
        "ATR_WARN": 4.5,
        "RSI_WARN_HIGH": 58,
        "RSI_WARN_LOW": 32,
    },
    "SQUEEZE": {"BB_WIDTH_MAX": 5.0, "DC_ATR_RATIO_MAX": 1.0},
    "CVD_LATERAL": {"FULL_SCORE_BELOW": 0.15, "ZERO_SCORE_ABOVE": 0.30},
    "DIRECTION": {"LONG_MIN_SCORE": 6.5, "SHORT_MAX_SCORE": 4.5},
}

# Default pairs user confirmed (USDT perps)
DEFAULT_PAIRS: list[str] = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "TRX/USDT",
    "SUI/USDT", "HYPE/USDT", "XRP/USDT", "XLM/USDT",
]

SIG_TIPS: dict = {
    "Trend Macro":     "Macro trend (30d). Checks price vs AVWAP14d/30d, CVD30d, and Structure30d. 3 of 4 conditions = confirmed direction.",
    "Trend Swing":     "Swing trend (5d). Checks price vs AVWAP5d, CVD5d, and 24h Flow together. DIV signals warn of potential reversals.",
    "Presiune":        "Buy/sell pressure. Combines 24h Flow, 7d OI change, and CVD5d. SQUEEZE RISK = positive flow + OI falling (short flush).",
    "Calitate Trend":  "CVD alignment across all 3 horizons (5d/14d/30d). FULL ACCUM = all positive = high-confidence bull signal.",
    "Setup":           "Entry signal quality. Liquidity sweep + flow + OI = best setup. POC near + CVD + structure = secondary entry.",
    "Risc":            "Risk level. HIGH = RSI extreme + extreme flow. MEDIUM = structure timeframe conflict or OI/flow accelerating together.",
    "Bot Grid":        "Grid bot suitability. RECOMMENDED when CVD5d is lateral (low delta) + no strong directional trend present.",
    "FVG":             "Fair Value Gap proximity (last 100 4H candles). * = structure confirms. FILLING = price entering the imbalance zone.",
    "EMA Trend":       "EMA50 vs EMA200 relationship on 4H. BULL/PULLBACK = in bull trend but pulling back to EMA50 (potential entry zone).",
    "Vol Spike":       "Volume spike detection vs 20-candle average (>=2x = spike). Bull spike above AVWAP5d = breakout. Bear spike below = breakdown.",
    "Donchian":        "20/55-period Donchian channels on 4H. Breakouts signal trend start. Tight channel vs ATR = squeeze (grid-friendly).",
    "Squeeze":         "BB width compressed + Donchian/ATR ratio tight. Grids thrive in squeezes. Breakouts end the grid window.",
}

LEGENDS: list[tuple[str, str]] = [
    ("RSI (14)", "Momentum on 4H. >70 overbought, <30 oversold. Much heavier signal than 1H RSI."),
    ("ATR (14)", f"Average True Range 4H. SL = {CFG['SL_ATR_MULT']}-2xATR4H. Values much larger than 1H ATR."),
    ("Flow% 24h", f"Buy vs sell pressure on 1H x24. >+{CFG['FLOW_STRONG']}%=buy dominant. <-{CFG['FLOW_STRONG']}%=sell dominant."),
    ("POC 5d/14d", "Max-volume price zone. Price above=support, below=resistance. 2/3 POC confluence=strong zone."),
    ("AVWAP 5d/14d/30d", "Volume-weighted avg price. Price below all 3=macro bearish. Above all 3=confirmed bull."),
    ("CVD 5d/14d/30d", "Cumulative Volume Delta. [ACC]=accumulation, [DIS]=distribution. All DIS=robust 4H bear."),
    ("EMA 50/200", "Standard trend filter. EMA50>EMA200+price above=uptrend. Golden/death cross=trend change."),
    ("Vol Spike", f">={CFG['VOL_SPIKE_MULT']}xavg=spike. Bull spike above AVWAP=breakout. Bear spike below=breakdown."),
    ("Structure 4H/30d", "Bullish=HH+HL. Bearish=LH+LL. Conflict between 4H and 30d=elevated risk."),
    ("OI/OI% 7d", "Open Interest. OI up+price up=real bull. OI up+price down=short buildup/squeeze risk."),
    ("FVG (Fair Value Gap)", "Institutional imbalance on 4H. *=confirmed by structure. BULL FVG=support, BEAR=resistance."),
    ("Donchian 20/55", "Price breakouts from the 20- or 55-candle high/low. Grid viability drops on a confirmed breakout."),
    ("Squeeze", "BB bandwidth compressed + Donchian/ATR tight. Prime grid window — expect range-bound action."),
    (
        f"Score 0-10",
        f"Grid Score >= {GRID_CONFIG['DIRECTION']['LONG_MIN_SCORE']} for Long Grid, < {GRID_CONFIG['DIRECTION']['SHORT_MAX_SCORE']} for Short. Components: ADX(3), BB(2), CVD lateral(1.5), POC(2), RSI(1), Funding(0.5). API: Binance primary, Bybit fallback.",
    ),
]
