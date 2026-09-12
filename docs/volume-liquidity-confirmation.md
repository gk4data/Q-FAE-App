# Volume and liquidity confirmation

Q-FAE combines participation and execution quality only after the latest completed one-minute feature snapshot is available. It retains the raw inputs alongside every classification:

- same-minute relative volume (RVOL);
- recent volume-acceleration ratio;
- bid/ask spread in basis points;
- cumulative traded value;
- spread and traded-value filter results;
- order-book depth imbalance as supporting context, not a hard gate.

## Classification contract

| Confirmation | Meaning |
| --- | --- |
| `strong_confirmation` | RVOL and acceleration are both strong, and both liquidity filters pass. |
| `confirmed` | Participation is active and both liquidity filters pass. |
| `liquid_but_unconfirmed` | Execution quality passes, but volume is mixed or quiet. |
| `volume_without_full_liquidity` | Volume is active, but one or more liquidity checks are unavailable. |
| `rejected` | Spread is too wide or cumulative traded value is too low, even if volume is high. |
| `insufficient` | Too little volume/liquidity evidence is available. |

Default thresholds are configuration rather than hidden model weights: active RVOL `1.0x`, strong RVOL `1.5x`, active acceleration `1.0x`, and strong acceleration `1.25x`. Spread and traded-value limits remain the existing configurable feature-engine filters. These defaults must be validated through point-in-time backtesting before being used in a ranked strategy.

The result is included in `GET /api/v1/market/evidence` and is also available directly from `GET /api/v1/market/confirmations`.

