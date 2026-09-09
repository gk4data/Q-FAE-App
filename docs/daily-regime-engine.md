# Daily regime engine

The daily regime engine provides context for intraday evidence. It does not assign a score and no individual horizon can accept or reject a stock.

This matters during trend transitions: a stock may have a negative 250-session return while its 5- and 20-session momentum, volume participation, structure, and relative strength show that a new regime is forming. Q-FAE preserves that disagreement instead of averaging it away.

## Inputs

- Up to 300 official Upstox daily OHLCV candles for each pilot equity.
- Matching daily history for NIFTY 50 and the explicitly mapped NIFTY sector index.
- During the session, a provisional daily candle aggregated from completed one-minute candles. It replaces, rather than duplicates, a same-date historical candle.

## Independent evidence groups

| Group | Measurements |
| --- | --- |
| Horizon performance | Stock return and excess return versus NIFTY and sector over 5, 20, 60, 120, and 250 sessions. Unavailable history remains `N/A`. |
| Trend | SMA 20/50/100/200, distance above SMA 20/50, five-session SMA20 slope, ten-session SMA50 slope, alignment, and regime classification. |
| Structure | Distance to prior 20/60-session highs, drawdown from the prior 252-session high, location and range within the latest 20 sessions, positive-close ratio, and 20-session path efficiency. |
| Participation | For completed days, volume versus the preceding 20 full sessions. During market hours, cumulative volume versus prior sessions at the same minute-of-day. Also includes the ratio of average up-day volume to average down-day volume. The comparison basis is exposed with every value. |
| Volatility | ATR14, ATR%, ATR14/ATR50, and latest true range versus the prior ATR14 baseline. |

## Interpretation policy

Evidence and cautions are labels, not weights:

- `short_term_strength_despite_weak_long_history` explicitly identifies a possible transition.
- `weak_250d_history_not_a_veto` documents long-term weakness without blocking the stock.
- High-volume advances, benchmark outperformance, emerging/established uptrends, and proximity to highs remain separate evidence.
- Extension, low participation, and unusually large ranges remain separate cautions.

Future backtests will decide whether combinations have predictive value. Until then, Q-FAE exposes the measurements without presenting a trade recommendation.
