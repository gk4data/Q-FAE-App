# Validated evidence confluence

Q-FAE combines its implemented measurements into four transparent pillars without strategy weights or a trade recommendation:

| Pillar | Validated inputs |
| --- | --- |
| Intraday technical | Current-session freshness, VWAP position and slope, latest ready opening range, five-minute momentum, and trend efficiency. |
| Daily trend/regime | No future-dated data, history-quality label, trend regime, moving-average alignment/slope, and price structure. |
| NIFTY and sector strength | Intraday performance versus NIFTY and the explicitly mapped sector index, current market tape, and 20/60-session relative performance. |
| Volume and liquidity | Same-minute RVOL, volume acceleration, spread filter, and cumulative traded-value filter. |

Each available check contributes either supportive evidence or a caution within its own pillar. The confluence label (`strong_support`, `supportive`, `mixed`, `caution`, or `insufficient`) counts pillar classifications equally; it is not a weighted score. Missing, stale, limited-history, unmapped-sector, and future-dated inputs remain visible in `validation_notes` rather than being converted to neutral zeros.

The dashboard and `GET /api/v1/market/evidence` expose these raw results. Pilot-v1 consumes them through the separately versioned [opportunity-ranking layer](opportunity-ranking.md). The ranking weights and thresholds are visibly provisional and must be calibrated with point-in-time outcomes before they are treated as predictive.
