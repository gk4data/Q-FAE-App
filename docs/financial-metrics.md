# Versioned financial metrics

Q-FAE calculates financial metrics deterministically from each immutable Upstox financial-result snapshot. Calculations are stored by source snapshot and calculation version, so revised provider statements and future formula changes remain auditable.

## Implemented calculations

- Quarterly revenue, operating-profit and net-profit growth versus the preceding quarter.
- Quarterly revenue, operating-profit and net-profit growth versus the same quarter in the previous year.
- Current operating and net margin, plus QoQ and YoY changes in percentage points.
- Annual operating cash flow divided by annual net profit as cash conversion.
- Explicit total borrowings, annual borrowing change and debt-to-equity when matching statement lines exist.
- Total liabilities and annual change, kept distinct from debt.
- Current ROE and ROCE from Upstox key ratios.
- Basic EPS, annual EPS growth and five-period EPS history from the detailed annual income statement.

## Safety rules

- Profit growth is unavailable when the comparison-period profit is zero or negative; a turnaround is not represented as a misleading percentage.
- Total liabilities are never labelled as debt.
- Debt and debt-to-equity remain unavailable unless explicit borrowing and equity lines are present.
- Cash conversion matches operating cash flow and net profit by reporting period; mismatched years are not divided.
- Missing inputs remain in the `unavailable` list and reduce `data_quality` to `partial` or `unavailable`.
- These metrics remain independent facts. Available fields feed the bounded fundamental component of the provisional opportunity score; missing fields reduce score coverage and remain visible.

## API and refresh

- `GET /api/v1/market/financial-metrics`
- `GET /api/v1/market/financial-metrics?instrument_key=NSE_EQ%7C...`
- `GET /api/v1/market/financial-metrics?latest_only=true` for one latest snapshot per stock

Both **Prepare 100 stocks** and **Check financial results** calculate and persist metrics after fetching or reusing a financial-result snapshot.

The dashboard's **Financials (Qtrly/Yearly)** tab reads the latest stored snapshot for each pilot stock when the tab is opened. The five-second live-market refresh does not reload these stable metrics, and opening the tab does not call Upstox; provider requests occur only through the preparation and financial-result-check workflows.

## Provider contracts

- [Upstox income statement](https://upstox.com/developer/api-documentation/get-income-statement/)
- [Upstox cash flow](https://upstox.com/developer/api-documentation/get-cash-flow/)
- [Upstox balance sheet](https://upstox.com/developer/api-documentation/get-balance-sheet/)
- [Upstox key ratios](https://upstox.com/developer/api-documentation/get-key-ratios/)
