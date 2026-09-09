# Intraday feature engine

Q-FAE calculates one explainable feature snapshot per pilot stock after each completed one-minute candle. These values are inputs, not trade recommendations. No composite score, direction weight, or execution decision is applied yet.

## Feature definitions

| Group | Current calculation | State or filter |
| --- | --- | --- |
| VWAP | Session cumulative typical price (`high + low + close`) / 3, weighted by one-minute volume. Position is close versus VWAP. Slope is the five-minute VWAP percentage change divided by five. | `above`, `below`, `at` |
| Opening gap | First one-minute open versus previous close. Gap/ATR preserves the sign. Retention is `(latest close - previous close) / (open - previous close)`. | `extending`, `holding`, `fading`, `filled_or_reversed`, `flat_open` |
| Opening ranges | High and low of candles beginning 09:15 through the first 5, 15, or 30 minutes. Latest completed close is classified relative to each range. | `above`, `inside`, `below`, or `pending` |
| Relative strength | Stock session return minus the completed-minute NIFTY 50 return and, when an explicit mapping exists, minus its completed-minute NIFTY sector-index return. Pilot percentile ranks the stock session return among calculable pilot names. | Missing sector mappings remain unavailable rather than using a guessed benchmark. |
| Momentum | Close-to-close returns over 1, 5, 15, and 30 minutes. Trend efficiency is absolute 15-minute displacement divided by the sum of absolute one-minute moves. The ten-minute bullish-candle fraction is also retained. | `strong_up`, `up`, `mixed`, `down`, `strong_down`, `forming` |
| Volume | Latest completed-minute volume, RVOL for the same minute-of-day against prior sessions, and mean volume of the latest 3 minutes divided by the preceding 5 minutes. | `high_relative`, `accelerating`, `active`, `quiet`, `unavailable` |
| Pullback | Direction comes from session open to latest close. Distance is measured from the favorable session extreme. Recovery measures where the close sits inside the session range. Countertrend volume compares opposing candle volume with directional candle volume over the latest 10 minutes. | `holding_extreme`, `orderly`, `deep_or_heavy`, `no_direction` |
| ATR / volatility | Simple mean true range from up to 14 completed prior sessions, reconstructed from one-minute candles. Also exposes ATR%, session range%, and session range/ATR. | `normal`, `elevated` at 0.7 ATR, `expanded` at 1 ATR |
| Spread / liquidity | Top-of-book spread in basis points, cumulative traded value (`LTP * total traded volume`), and total depth imbalance `(buy - sell) / (buy + sell)`. | Pass currently requires spread <= 25 bps and traded value >= Rs 1 crore. Either failure is `reject`; incomplete inputs are `partial`. |

## Timing and data quality

- Calculations use only the latest completed candle; the still-forming minute is excluded.
- The opening-range feature stays pending until its full 5/15/30-minute window has elapsed.
- Each snapshot includes `data_quality` and an `unavailable` list. A missing input remains `N/A`; it is never replaced with zero.
- Features are kept in Redis and exposed through `GET /api/v1/market/features` in approved-universe order.
- The dashboard polls the latest snapshot every five seconds, while calculation cadence remains once per minute.

The historical bootstrap retains 14 recent sessions. Upstox permits a maximum one-month date span for 1-to-15-minute Historical Candle V3 requests, so Q-FAE requests at most 29 calendar days and keeps the newest configured exchange sessions.

## Configurable thresholds

- `QFAE_FEATURE_MAX_SPREAD_BPS` (default `25`)
- `QFAE_FEATURE_MIN_TRADED_VALUE_INR` (default `10000000`)
- `QFAE_MARKET_HISTORY_DAYS` (default `14`)
- `QFAE_DAILY_HISTORY_SESSIONS` (default `300`)

These are pilot defaults. They must be evaluated by liquidity bucket and point-in-time backtesting before becoming model or execution rules.
