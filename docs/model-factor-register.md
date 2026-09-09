# Q-FAE Model Factor Register

This document records the approved candidate information set for Q-FAE's future opportunity and continuation model. The application should preserve these raw variables and derived features so their weights and interactions can be evaluated later.

## Interpretation rule

Every factor below must be considered, but no factor is assumed to be permanently bullish, bearish, or predictive. Its direction depends on the trade side and context. For example, a supported gap-up may favour long continuation, while a failed gap-up may favour reversal. The final model must learn or validate these relationships from point-in-time Indian-market data after costs.

Time horizons are independent evidence, not a hierarchy of vetoes. Weak 120/250-session performance must not automatically reject fresh 5/20/60-session strength, a trend transition, or a high-quality intraday move. Conflicting horizons must remain visible to the model and user rather than being averaged into one opaque trend value.

## Catalyst and fundamental factors

- Earnings, revenue, margin, and cash-flow surprises
- Agreement or disagreement between earnings and revenue surprises
- Guidance upgrades, downgrades, withdrawals, and management confidence
- Concall tone, management commentary, and changes from prior guidance
- Material orders, with order value scaled by revenue and market capitalisation
- Regulatory approvals, rejections, investigations, and policy changes
- Mergers, acquisitions, divestments, capital raising, and buybacks
- Analyst estimate and recommendation revisions where licensed data is available
- Fundamental quality: growth, ROCE/ROE, leverage, cash conversion, earnings stability, and promoter/institutional changes
- Catalyst freshness, novelty, source credibility, materiality, and whether it appears priced in
- Supporting or conflicting company, industry, customer, supplier, and sector news

## Pre-open and opening factors

- Official open versus corporate-action-adjusted previous close
- Raw gap percentage and gap size normalised by daily ATR
- Stock gap relative to NIFTY and its sector
- Indicative equilibrium price, tradable quantity, and buy/sell imbalance when reliably available
- Open inside or outside the previous day's range
- Gap retention and gap-fill percentage after 1, 5, 15, and 30 minutes
- Opening-drive strength and early rejection/reversal
- Five-, fifteen-, and thirty-minute opening-range breaks, retests, and failed breaks

## Price and trend-quality factors

- Daily returns over 5, 20, 60, 120, and 250 sessions, treated as contextual evidence rather than pass/fail rules
- Price versus 20/50/100/200-session averages, their slopes, alignment, and emerging-regime transitions
- Returns and momentum over multiple horizons, including 1, 5, 15, 30, and 60 minutes
- Relative strength versus NIFTY, the relevant sector, and the approved universe
- Higher-high/higher-low or lower-high/lower-low structure
- Trend efficiency: net directional movement relative to total path travelled
- Candle close location, body/range ratio, wick asymmetry, and consecutive directional closes
- Pullback depth, duration, recovery speed, and impulse-versus-pullback volume
- Distance from intraday and multi-day highs/lows and available room before major levels
- Daily Classic Pivots and CPR, plus interaction with support/resistance levels when implemented
- Previous-day high/low/close, recent swing levels, and 20/52-week extremes
- ATR, realised volatility, volatility expansion/contraction, and abnormal range

## VWAP, volume, and participation factors

- Price above/below VWAP, distance from VWAP, and VWAP slope
- Time and number of closes held on one side of VWAP
- VWAP break, reclaim, rejection, and retest quality
- One-minute volume and cumulative session volume
- Same-minute-of-day relative volume using prior comparable sessions
- Volume acceleration and volume concentration during directional impulses
- Turnover/traded value and turnover relative to the stock's normal activity
- Participation persistence rather than a single volume spike

## Market, sector, and regime factors

- NIFTY 50 and NIFTY Bank direction and strength
- India VIX level, change, and volatility regime
- Market and approved-universe breadth, including advance/decline measures
- Sector direction, breadth, leadership, and stock-sector agreement
- Cross-sectional ranking and dispersion of stock returns
- Market trend, range, risk-on/risk-off, and high-correlation regimes
- Time of day, day of week, expiry/event days, and known macro-event windows

## Liquidity and order-flow factors

- Bid/ask spread in basis points and its stability
- Best-depth and multi-level depth quantities when available
- Order-book imbalance, bid/ask replenishment, and imbalance persistence
- Total buy/sell quantity, last-trade quantity, and trade-arrival intensity
- Estimated slippage, market impact, and executable position size
- Data freshness, feed gaps, abnormal prints, and liquidity deterioration

Displayed orders may be cancelled or misleading, so order-book variables must not dominate the model without execution-aware validation.

## News and community-attention factors

- Rate of change in credible news and community mentions
- Number and diversity of independent sources
- Sentiment direction, strength, disagreement, and sudden reversals
- Confirmation by official exchange/company disclosures
- Agreement between attention, price, volume, and liquidity
- Source reliability and manipulation/pump-risk indicators

Community attention is an attention/catalyst feature, not a standalone recommendation or truth signal. Unverified tips and raw follower counts must not directly create a trade decision.

## Candidate model components

The final decision layer should retain explainable component scores for:

1. Catalyst strength
2. Participation strength
3. Price and trend quality
4. Market and sector alignment
5. Liquidity and execution quality
6. Fundamental quality and risk
7. News/community confirmation and manipulation risk

Weights, thresholds, interactions, and long/short direction will be decided only after backtesting. Q-FAE should show the underlying reasons, invalidation conditions, data freshness, and confidence—not only a single score.

## Validation requirements

- Use point-in-time data and prevent look-ahead or survivorship bias.
- Adjust historical reference prices for corporate actions.
- Use same-time-of-day baselines for intraday volume and liquidity.
- Include brokerage, fees, taxes, spread, slippage, and realistic execution delay.
- Test out of sample, across market regimes, sectors, liquidity groups, and long/short directions.
- Track missing/stale inputs explicitly; do not silently replace them with favourable values.
- Prefer a smaller robust feature set if additional factors do not improve out-of-sample results.

Full-universe retention and incremental synchronization must follow the [historical-data storage policy](historical-data-storage.md).
