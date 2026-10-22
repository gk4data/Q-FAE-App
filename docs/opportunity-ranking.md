# Explainable opportunity ranking

Q-FAE model-v5 ranks liquidity-Active stocks from the full approved universe for **long-continuation research** after each completed market minute. It is an explainable deterministic baseline, not a trained prediction model or trading recommendation. Previous-session turnover does not decide which companies receive a score, and live execution quality does not alter the opportunity score or rank.

## Provisional weights

| Component | Default weight |
| --- | ---: |
| Price and trend quality | 30% |
| Volume participation | 20% |
| NIFTY and sector alignment | 20% |
| Fundamental quality and growth | 15% |

The values are configurable with the `QFAE_SCORE_WEIGHT_*` environment variables and normalized to 100. Every response records the effective weights and model version.

## Score construction

1. Each component produces a bounded 0–100 score from its available point-in-time inputs.
2. Each component separately reports input coverage. Missing values are not replaced with zero or a neutral value.
3. `evidence_score` is the weighted score over available inputs.
4. `coverage_adjusted_score` applies the missing-data penalty, so a sparse candidate cannot outrank a fully observed candidate merely because its few known inputs look good.
5. The score is multiplied by signal persistence: confirmed `1.00`, building `0.90`, neutral/unavailable `0.80`, weakening `0.60`, and failed `0.35`.
6. Rolling continuity and median traded value determine admission to the Active universe. Stale intraday evidence or less than 45% score coverage can still invalidate an opportunity.
7. For Active stocks, current spread, D5 slippage, depth stability and other pre-trade checks are attached as execution cautions. They cannot change opportunity eligibility, score, rank, Focus state or Alpha Matrix position.
8. Watch-only stocks retain their directional opportunity score so strong signals outside the Active universe can be audited separately.

The endpoint returns component scores, weights, contribution points, positive factors, cautions, missing inputs and invalidation reasons. Ranks are recalculated cross-sectionally across all currently observed Active stocks in the approved universe.

## Fundamental safeguards

- Growth and margin changes are bounded before entering the score so extreme percentages cannot dominate.
- Cash conversion, ROE, ROCE and EPS trend contribute only when available.
- Generic debt thresholds are not applied to banks, NBFCs or other mapped financial sectors.
- Financial facts retain their independent versioned source snapshot.

## Calibration boundary

`calibration_status=provisional_not_backtested` is deliberate. The default weights and status thresholds are engineering priors chosen for a usable baseline. They must be evaluated against the stored 5/15/30/60-minute and end-of-day outcomes, after spread, slippage, fees and execution delay, before production use.

The current version does not rank short opportunities. A short model requires separately validated bearish persistence, direction-aware participation and risk behavior rather than simply reversing the long score.

## API and UI

- `GET /api/v1/market/opportunities`
- The dashboard displays Active-universe ranks separately from **High signal, outside active universe** observations. It also displays final score, evidence strength, coverage, persistence multiplier, every component contribution, leading evidence, model cautions and separate execution cautions.
- The **Alpha Matrix** plots the current final Opportunity Score on the horizontal axis and a provisional confidence proxy on the vertical axis. The confidence proxy is score coverage multiplied by the persistence multiplier; an active hard invalidation caps it in the low-confidence region.
- Bubble size represents participation strength, colour represents opportunity status, and selecting a bubble opens the consolidated stock-detail view.
- The provisional quadrant boundary is Opportunity Score 70 and confidence proxy 65. These are visual research thresholds rather than buy instructions and must be recalibrated from point-in-time outcomes.
