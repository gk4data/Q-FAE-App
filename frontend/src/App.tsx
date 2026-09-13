import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import * as echarts from "echarts/core";
import { ScatterChart } from "echarts/charts";
import { AriaComponent, GridComponent, MarkAreaComponent, TooltipComponent } from "echarts/components";
import { LabelLayout } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([ScatterChart, AriaComponent, GridComponent, MarkAreaComponent, TooltipComponent, LabelLayout, CanvasRenderer]);

type AuthStatus = { configured: boolean; authenticated: boolean; expires_at: string | null };

type RuntimeStatus = {
  cadence_seconds: number;
  pilot_size: number;
  redis_available: boolean;
  database_available: boolean;
  bootstrap: { state: string; total: number; processed: number; history_loaded: number; minute_history_persisted: number; minute_profiles_built: number; daily_history_loaded: number; daily_history_persisted: number; benchmark_daily_loaded: number; sectors_loaded: number; corporate_actions_synced: number; corporate_actions_stored: number; corporate_actions_assessed: number; corporate_adjustments_built: number; corporate_documents_stored: number; corporate_financial_contexts: number; financial_results_reused: number; corporate_ai_analyzed: number; corporate_outcomes_evaluated: number; errors: number };
  live: { state: string; connected: boolean; subscribed: number; last_message_at: string | null; scheduled_stop_at: string | null; error: string | null };
  reconciliation: { state: string; session_date: string | null; total: number; processed: number; matched: number; with_differences: number; official_only: number; missing: number; errors: number };
};

type WatchlistItem = {
  instrument_key: string;
  symbol: string;
  company_name: string;
  sector: string | null;
  ltp: number | null;
  change_percent: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  relative_volume: number | null;
  spread_bps: number | null;
  updated_at: string | null;
  data_state: "live" | "cached" | "history" | "waiting";
};

type BenchmarkState = {
  instrument_key: string;
  ltp: number | null;
  previous_close: number | null;
  change_percent: number | null;
  direction: string;
  updated_at: string | null;
  fresh: boolean;
};

type SectorIndexState = BenchmarkState & { sector: string };

type MarketContext = {
  as_of: string;
  cadence_seconds: number;
  nifty_50: BenchmarkState;
  nifty_bank: BenchmarkState;
  india_vix: BenchmarkState;
  sector_indices: SectorIndexState[];
  universe_size: number;
  fresh_instruments: number;
  stale_instruments: number;
  advancers: number;
  decliners: number;
  unchanged: number;
  advance_decline_ratio: number | null;
  median_spread_bps: number | null;
  liquid_instruments: number;
  relative_volume_leaders: Array<{
    instrument_key: string;
    symbol: string;
    relative_volume: number;
    candle_timestamp: string;
  }>;
};

type MarketRegime = {
  as_of: string;
  state: "risk_on" | "mixed" | "risk_off" | "insufficient";
  observations: number;
  breadth_ratio: number | null;
  breadth_persistence: number | null;
  sector_participation: number | null;
  vix_acceleration_percent: number | null;
  unavailable_inputs: string[];
};

type OpeningRangeFeatures = {
  minutes: number;
  ready: boolean;
  high: number | null;
  low: number | null;
  width_percent: number | null;
  breakout_percent: number | null;
  position: string;
};

type StockFeatures = {
  instrument_key: string;
  symbol: string;
  sector: string | null;
  as_of: string;
  candle_timestamp: string;
  data_quality: string;
  unavailable: string[];
  vwap: { value: number | null; position_percent: number | null; slope_5m_percent_per_minute: number | null; state: string };
  gap: { gap_percent: number | null; gap_atr: number | null; retention_percent: number | null; state: string };
  opening_ranges: OpeningRangeFeatures[];
  relative_strength: {
    session_return_percent: number | null;
    versus_nifty_percent: number | null;
    sector_index: string | null;
    versus_sector_percent: number | null;
    universe_percentile: number | null;
  };
  momentum: {
    return_1m_percent: number | null;
    return_5m_percent: number | null;
    return_15m_percent: number | null;
    return_30m_percent: number | null;
    efficiency_ratio_15m: number | null;
    bullish_candle_ratio_10m: number | null;
    state: string;
  };
  volume: { completed_minute_volume: number | null; acceleration_ratio: number | null; relative_volume: number | null; state: string };
  pullback: {
    direction: string;
    distance_from_extreme_percent: number | null;
    recovery_fraction: number | null;
    countertrend_volume_ratio: number | null;
    quality: string;
  };
  volatility: {
    atr: number | null;
    atr_percent: number | null;
    atr_sessions: number;
    session_range_percent: number | null;
    session_range_atr: number | null;
    state: string;
  };
  liquidity: {
    spread_bps: number | null;
    total_traded_value_inr: number | null;
    depth_imbalance: number | null;
    passes_spread_filter: boolean | null;
    passes_traded_value_filter: boolean | null;
    state: string;
  };
};

type HorizonPerformance = {
  sessions: number;
  stock_return_percent: number | null;
  nifty_return_percent: number | null;
  versus_nifty_percent: number | null;
  sector_return_percent: number | null;
  versus_sector_percent: number | null;
};

type DailyRegime = {
  instrument_key: string;
  symbol: string;
  sector: string | null;
  as_of: string;
  data_through: string;
  sessions_available: number;
  data_quality: string;
  horizon_performance: HorizonPerformance[];
  trend: {
    sma_20: number | null; sma_50: number | null; sma_100: number | null; sma_200: number | null;
    above_sma_20_percent: number | null; above_sma_50_percent: number | null;
    sma_20_slope_5d_percent: number | null; sma_50_slope_10d_percent: number | null;
    alignment: string; regime: string;
  };
  structure: {
    distance_to_20d_high_percent: number | null; distance_to_60d_high_percent: number | null;
    drawdown_from_252d_high_percent: number | null; close_location_20d: number | null;
    range_20d_percent: number | null; positive_close_ratio_20d: number | null;
    trend_efficiency_20d: number | null; state: string;
  };
  participation: {
    latest_volume: number | null; relative_volume: number | null; relative_volume_basis: string;
    up_down_volume_ratio_20: number | null; high_volume_direction: string;
  };
  volatility: {
    atr_14: number | null; atr_14_percent: number | null; atr_14_vs_50: number | null;
    latest_range_atr: number | null; state: string;
  };
  evidence: string[];
  cautions: string[];
};

type EvidencePillar = {
  key: string;
  label: string;
  state: "supportive" | "mixed" | "caution" | "unavailable";
  available_checks: number;
  supportive_checks: number;
  caution_checks: number;
  evidence: string[];
  cautions: string[];
};

type OpportunityEvidence = {
  instrument_key: string;
  symbol: string;
  sector: string | null;
  as_of: string;
  data_quality: string;
  confluence: "strong_support" | "supportive" | "mixed" | "caution" | "insufficient";
  pillars: EvidencePillar[];
  flow_liquidity: {
    data_quality: string;
    relative_volume: number | null;
    volume_acceleration: number | null;
    spread_bps: number | null;
    traded_value_inr: number | null;
    depth_imbalance: number | null;
    passes_spread_filter: boolean | null;
    passes_traded_value_filter: boolean | null;
    volume_state: string;
    liquidity_state: string;
    confirmation: string;
    evidence: string[];
    cautions: string[];
  };
  signal_persistence: null | {
    state: "building" | "confirmed" | "weakening" | "failed" | "neutral";
    supportive_minutes: number;
    caution_minutes: number;
    observed_minutes: number;
    transition: string | null;
    reason: string;
  };
  risk_assessment: null | {
    eligible: boolean;
    status: "pass" | "partial" | "rejected";
    reference_order_value_inr: number;
    estimated_buy_slippage_bps: number | null;
    estimated_sell_slippage_bps: number | null;
    distance_to_upper_circuit_percent: number | null;
    distance_to_lower_circuit_percent: number | null;
    gates: Array<{ key: string; status: string; reason: string }>;
  };
  corporate_action_context: null | {
    state: "positive" | "negative" | "neutral" | "unavailable";
    active_events: number;
    maximum_materiality: number | null;
    deterministic_sentiment: number | null;
    ai_impact_score: number | null;
    effective_score: number | null;
    evidence: string[];
    cautions: string[];
  };
  validation_notes: string[];
};

type OpportunityScoreComponent = {
  key: string;
  label: string;
  weight_percent: number;
  score: number | null;
  coverage_percent: number;
  contribution_points: number;
  positive_factors: string[];
  cautions: string[];
  unavailable_inputs: string[];
};

type RankedOpportunity = {
  rank: number | null;
  instrument_key: string;
  symbol: string;
  sector: string | null;
  as_of: string;
  current_market_price: number | null;
  session_return_percent: number | null;
  score: {
    model_version: string;
    strategy: string;
    calibration_status: string;
    evidence_score: number;
    coverage_percent: number;
    coverage_adjusted_score: number;
    persistence_multiplier: number;
    final_score: number;
    eligible: boolean;
    status: "high_priority" | "promising" | "watch" | "low_conviction" | "ineligible" | "insufficient_data";
    weights: Record<string, number>;
    components: OpportunityScoreComponent[];
    top_positive_factors: string[];
    top_cautions: string[];
    invalidation_reasons: string[];
  };
};

type CorporateActionAssessment = {
  event_id: string;
  assessment_version: number;
  instrument_key: string;
  symbol: string;
  category: string;
  direction: "positive" | "negative" | "neutral" | "contextual";
  materiality_score: number;
  sentiment_score: number;
  confidence: number;
  impact_horizon: string;
  reference_price: number | null;
  reference_price_date: string | null;
  derived_metrics: Record<string, number | string | null>;
  evidence: string[];
  cautions: string[];
  requires_ai_review: boolean;
};

type CorporateActionAIAnalysis = {
  event_id: string;
  analysis_version: number;
  status: "complete" | "unavailable";
  impact_score: number | null;
  impact_probability: number | null;
  confidence: number | null;
  impact_horizon: string | null;
  rationale: string | null;
  citation_document_ids: string[];
  grounded: boolean;
  error: string | null;
};

type FinancialResultCheckReport = {
  generated_at: string;
  cache_days: number;
  total: number;
  fetched: number;
  reused: number;
  unavailable: number;
  failed: number;
  items: Array<{
    instrument_key: string;
    symbol: string;
    state: "fetched" | "reused" | "unavailable" | "failed";
    reason: string;
    quarterly_period: string | null;
    annual_period: string | null;
    quarterly_available: boolean;
    annual_available: boolean;
    snapshot_at: string | null;
    cache_fresh: boolean;
  }>;
};

type FinancialMetricSnapshot = {
  source_snapshot_id: string;
  calculation_version: number;
  isin: string;
  instrument_key: string;
  symbol: string;
  latest_quarter: string | null;
  latest_annual_period: string | null;
  growth: {
    revenue_qoq_percent: number | null;
    revenue_yoy_percent: number | null;
    operating_profit_qoq_percent: number | null;
    operating_profit_yoy_percent: number | null;
    net_profit_qoq_percent: number | null;
    net_profit_yoy_percent: number | null;
  };
  margins: {
    operating_margin_percent: number | null;
    operating_margin_qoq_change_pp: number | null;
    operating_margin_yoy_change_pp: number | null;
    net_margin_percent: number | null;
    net_margin_qoq_change_pp: number | null;
    net_margin_yoy_change_pp: number | null;
  };
  capital: {
    operating_cash_conversion_percent: number | null;
    total_debt_crore: number | null;
    debt_yoy_change_percent: number | null;
    debt_to_equity: number | null;
    total_liabilities_crore: number | null;
    liabilities_yoy_change_percent: number | null;
    roe_percent: number | null;
    roce_percent: number | null;
  };
  eps: {
    latest_basic_eps: number | null;
    latest_period: string | null;
    yoy_growth_percent: number | null;
    history: Array<{ period: string; value: number | string }>;
  };
  data_quality: string;
  unavailable: string[];
  cautions: string[];
  formulas: Record<string, string>;
  calculated_at: string;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

const number = (value: number | null, digits = 2) =>
  value == null ? "—" : value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const integer = (value: number | null) => value == null ? "—" : value.toLocaleString("en-IN");
const signedPercent = (value: number | null) => value == null ? "N/A" : `${value > 0 ? "+" : ""}${number(value)}%`;
const percent = (value: number | null) => value == null ? "N/A" : `${number(value)}%`;
const multiple = (value: number | null) => value == null ? "N/A" : `${number(value)}x`;
const ratio = (value: number | null) => value == null ? "N/A" : number(value);
const tone = (value: number | null) => value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
const tradedValue = (value: number | null) => {
  if (value == null) return "N/A";
  if (value >= 10_000_000) return `Rs ${number(value / 10_000_000)} cr`;
  if (value >= 100_000) return `Rs ${number(value / 100_000)} lakh`;
  return `Rs ${integer(value)}`;
};

function Brand() {
  return (
    <div className="brand-lockup">
      <p className="brand-name" aria-label="Q FAE">
        <span>Q</span><i>&middot;</i><span>FAE</span><i className="brand-arrow" aria-hidden="true">&uarr;</i>
      </p>
      <p className="brand-full-form">Quantitative Financial Algorithms for Equity</p>
    </div>
  );
}

function LoginPage({ auth, backendError }: { auth: AuthStatus | null; backendError: boolean }) {
  const result = new URLSearchParams(window.location.search).get("auth");
  const startLogin = () => window.location.assign(`${apiBaseUrl}/auth/upstox/login`);

  return (
    <main className="auth-shell">
      <section className="brand-panel">
        <Brand />
        <h1>See the market<br />with more clarity.</h1>
        <p>Real-time Indian equity intelligence, built around evidence rather than noise.</p>
      </section>
      <section className="login-panel" aria-label="Upstox sign in">
        <p className="eyebrow">CONNECT DATA</p>
        <h2>Sign in to begin</h2>
        <p className="description">Connect your Upstox account to enable read-only market data access.</p>
        {result === "failed" && <p className="notice error">Sign-in could not be completed. Please try again.</p>}
        {result === "cancelled" && <p className="notice error">Sign-in was cancelled.</p>}
        {backendError && <p className="notice error">The Q-FAE backend is not running on port 8000.</p>}
        <button type="button" onClick={startLogin} disabled={!auth?.configured || backendError}>Continue with Upstox</button>
        {!auth && !backendError && <p className="status">Checking secure connection...</p>}
        {auth && !auth.configured && <p className="status">Upstox OAuth needs local configuration.</p>}
        <p className="fine-print">Your access token stays in the Q-FAE backend and is never sent to this page.</p>
      </section>
    </main>
  );
}

function ChangeValue({ value }: { value: number | null }) {
  const directionClass = value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
  return (
    <span className={`change-value ${directionClass}`}>
      {value == null ? "N/A" : `${value > 0 ? "+" : ""}${number(value)}%`}
    </span>
  );
}

function IndexCard({ name, state }: { name: string; state: BenchmarkState }) {
  return (
    <article className="index-card">
      <div className="index-name"><span className={`fresh-dot ${state.fresh ? "fresh" : ""}`} />{name}</div>
      <strong>{number(state.ltp)}</strong>
      <ChangeValue value={state.change_percent} />
    </article>
  );
}

function MarketContextPanel({ context, regime }: { context: MarketContext | null; regime: MarketRegime | null }) {
  if (!context) {
    return (
      <section className="context-card context-placeholder">
        <div><p className="eyebrow">MARKET CONTEXT</p><h2>Waiting for the first complete market minute</h2></div>
        <p>Start the live feed to calculate indices, breadth, sector strength, liquidity and RVOL leadership.</p>
      </section>
    );
  }

  const breadthTotal = context.advancers + context.decliners + context.unchanged;
  return (
    <section className="context-card">
      <div className="context-heading">
        <div><p className="eyebrow">MARKET CONTEXT</p><h2>One-minute market pulse</h2></div>
        <div className="context-status"><span className={`confluence-badge ${regime?.state ?? "insufficient"}`}>{regime?.state.replaceAll("_", " ") ?? "regime waiting"}</span><span>As of {new Date(context.as_of).toLocaleTimeString("en-IN")}</span></div>
      </div>

      <div className="index-grid">
        <IndexCard name="NIFTY 50" state={context.nifty_50} />
        <IndexCard name="NIFTY BANK" state={context.nifty_bank} />
        <IndexCard name="INDIA VIX" state={context.india_vix} />
        <article className="breadth-card">
          <span>Pilot breadth</span>
          <strong><i className="positive">{context.advancers} up</i><b>/</b><i className="negative">{context.decliners} down</i></strong>
          <small>{breadthTotal} active · A/D {context.advance_decline_ratio == null ? "N/A" : number(context.advance_decline_ratio)}</small>
        </article>
        <article className="breadth-card">
          <span>Data coverage</span>
          <strong>{context.fresh_instruments}/{context.universe_size}</strong>
          <small>{context.stale_instruments} stale · {context.liquid_instruments} with spread</small>
        </article>
        <article className="breadth-card">
          <span>Median spread</span>
          <strong>{context.median_spread_bps == null ? "N/A" : `${number(context.median_spread_bps)} bps`}</strong>
          <small>Across fresh pilot stocks</small>
        </article>
      </div>

      <div className="context-columns">
        <div className="context-section">
          <div className="section-label"><span>Sector indices</span><small>Strongest to weakest</small></div>
          <div className="sector-list">
            {context.sector_indices.map((sector) => (
              <div className="sector-row" key={sector.instrument_key}>
                <span><i className={`fresh-dot ${sector.fresh ? "fresh" : ""}`} />{sector.sector}</span>
                <ChangeValue value={sector.change_percent} />
              </div>
            ))}
          </div>
        </div>
        <div className="context-section rvol-section">
          <div className="section-label"><span>RVOL leaders</span><small>Latest completed minute</small></div>
          {context.relative_volume_leaders.length ? (
            <div className="leader-list">
              {context.relative_volume_leaders.slice(0, 6).map((leader, index) => (
                <div className="leader-row" key={leader.instrument_key}>
                  <b>{index + 1}</b><strong>{leader.symbol}</strong><span>{number(leader.relative_volume)}x</span>
                </div>
              ))}
            </div>
          ) : <p className="empty-copy">Waiting for comparable completed candles.</p>}
        </div>
      </div>
    </section>
  );
}

function MetricLine({ label, value, valueClass = "" }: { label: string; value: string; valueClass?: string }) {
  return <span className="metric-line"><small>{label}</small><b className={valueClass}>{value}</b></span>;
}

function DailyRegimePanel({ regimes }: { regimes: DailyRegime[] }) {
  return (
    <section className="table-card regime-card">
      <div className="table-heading">
        <div><h2>Daily regime evidence</h2><p>Independent horizons reveal established trends, pullbacks and new transitions</p></div>
        <span>Long history provides context; it never blocks fresh strength</span>
      </div>
      <div className="table-scroll">
        <table className="regime-table">
          <thead><tr><th>Stock</th><th>5 / 20 / 60 / 120 / 250 sessions</th><th>Trend alignment</th><th>Price structure</th><th>Participation</th><th>Volatility</th><th>Evidence and cautions</th></tr></thead>
          <tbody>
            {regimes.map((regime) => (
              <tr key={regime.instrument_key}>
                <td>
                  <strong>{regime.symbol}</strong>
                  <small>{regime.sessions_available} daily sessions</small>
                  <span className={`quality-badge ${regime.data_quality}`}>{regime.data_quality}</span>
                  <small className="factor-state">{regime.trend.regime.replaceAll("_", " ")}</small>
                </td>
                <td>
                  {regime.horizon_performance.map((horizon) => (
                    <span className="horizon-line" key={horizon.sessions}>
                      <small>{horizon.sessions}d</small>
                      <b className={tone(horizon.stock_return_percent)}>{signedPercent(horizon.stock_return_percent)}</b>
                      <i className={tone(horizon.versus_nifty_percent)}>vs N {signedPercent(horizon.versus_nifty_percent)}</i>
                      <i className={tone(horizon.versus_sector_percent)}>vs S {signedPercent(horizon.versus_sector_percent)}</i>
                    </span>
                  ))}
                </td>
                <td>
                  <MetricLine label="vs SMA20" value={signedPercent(regime.trend.above_sma_20_percent)} valueClass={tone(regime.trend.above_sma_20_percent)} />
                  <MetricLine label="vs SMA50" value={signedPercent(regime.trend.above_sma_50_percent)} valueClass={tone(regime.trend.above_sma_50_percent)} />
                  <MetricLine label="SMA20 slope" value={signedPercent(regime.trend.sma_20_slope_5d_percent)} valueClass={tone(regime.trend.sma_20_slope_5d_percent)} />
                  <MetricLine label="SMA50 slope" value={signedPercent(regime.trend.sma_50_slope_10d_percent)} valueClass={tone(regime.trend.sma_50_slope_10d_percent)} />
                  <small className="factor-state">{regime.trend.alignment} alignment</small>
                </td>
                <td>
                  <MetricLine label="to 20d high" value={signedPercent(regime.structure.distance_to_20d_high_percent)} valueClass={tone(regime.structure.distance_to_20d_high_percent)} />
                  <MetricLine label="to 60d high" value={signedPercent(regime.structure.distance_to_60d_high_percent)} valueClass={tone(regime.structure.distance_to_60d_high_percent)} />
                  <MetricLine label="from 252d high" value={signedPercent(regime.structure.drawdown_from_252d_high_percent)} />
                  <MetricLine label="20d range" value={percent(regime.structure.range_20d_percent)} />
                  <MetricLine label="20d efficiency" value={ratio(regime.structure.trend_efficiency_20d)} />
                  <small className="factor-state">{regime.structure.state.replaceAll("_", " ")}</small>
                </td>
                <td>
                  <MetricLine label="Relative volume" value={multiple(regime.participation.relative_volume)} />
                  <MetricLine label="Up/down volume" value={multiple(regime.participation.up_down_volume_ratio_20)} />
                  <MetricLine label="Latest volume" value={integer(regime.participation.latest_volume)} />
                  <small className="factor-state">{regime.participation.relative_volume_basis.replaceAll("_", " ")}</small>
                  <small className="factor-state">{regime.participation.high_volume_direction.replaceAll("_", " ")}</small>
                </td>
                <td>
                  <MetricLine label="ATR14" value={regime.volatility.atr_14 == null ? "N/A" : number(regime.volatility.atr_14)} />
                  <MetricLine label="ATR14 %" value={percent(regime.volatility.atr_14_percent)} />
                  <MetricLine label="ATR14 / ATR50" value={ratio(regime.volatility.atr_14_vs_50)} />
                  <MetricLine label="Latest range / ATR" value={multiple(regime.volatility.latest_range_atr)} />
                  <small className="factor-state">{regime.volatility.state.replaceAll("_", " ")}</small>
                </td>
                <td className="tag-cell">
                  {regime.evidence.map((item) => <span className="evidence-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
                  {regime.cautions.map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
                  {!regime.evidence.length && !regime.cautions.length && <small className="factor-state">No classified evidence yet</small>}
                </td>
              </tr>
            ))}
            {!regimes.length && (
              <tr><td className="feature-empty" colSpan={7}>Prepare the pilot stocks to load daily history and calculate regime evidence.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FeatureMatrix({ features }: { features: StockFeatures[] }) {
  const openingRange = (feature: StockFeatures, minutes: number) =>
    feature.opening_ranges.find((range) => range.minutes === minutes);

  return (
    <section className="table-card feature-card">
      <div className="table-heading">
        <div><h2>Intraday feature matrix</h2><p>Nine explainable factor groups, recalculated after every completed minute</p></div>
        <span>Raw factor detail behind the pilot opportunity score</span>
      </div>
      <div className="table-scroll">
        <table className="feature-table">
          <thead>
            <tr>
              <th>Stock</th><th>VWAP</th><th>Opening gap</th><th>Opening ranges</th><th>Relative strength</th>
              <th>Momentum</th><th>Volume</th><th>Pullback</th><th>ATR / volatility</th><th>Liquidity</th>
            </tr>
          </thead>
          <tbody>
            {features.map((feature) => {
              const ranges = [5, 15, 30].map((minutes) => ({ minutes, range: openingRange(feature, minutes) }));
              return (
                <tr key={feature.instrument_key}>
                  <td>
                    <strong>{feature.symbol}</strong>
                    <small>{feature.sector ?? "Sector unavailable"}</small>
                    <span className={`quality-badge ${feature.data_quality}`}>{feature.data_quality}</span>
                  </td>
                  <td>
                    <MetricLine label="Position" value={signedPercent(feature.vwap.position_percent)} valueClass={tone(feature.vwap.position_percent)} />
                    <MetricLine label="5m slope/min" value={signedPercent(feature.vwap.slope_5m_percent_per_minute)} valueClass={tone(feature.vwap.slope_5m_percent_per_minute)} />
                    <small className="factor-state">{feature.vwap.state}</small>
                  </td>
                  <td>
                    <MetricLine label="Gap" value={signedPercent(feature.gap.gap_percent)} valueClass={tone(feature.gap.gap_percent)} />
                    <MetricLine label="Retention" value={signedPercent(feature.gap.retention_percent)} valueClass={tone(feature.gap.retention_percent)} />
                    <small className="factor-state">{feature.gap.state.replaceAll("_", " ")}</small>
                  </td>
                  <td>
                    {ranges.map(({ minutes, range }) => (
                      <MetricLine
                        key={minutes}
                        label={`${minutes}m`}
                        value={range?.ready ? `${range.position} ${signedPercent(range.breakout_percent)}` : "forming"}
                        valueClass={range?.position === "above" ? "positive" : range?.position === "below" ? "negative" : ""}
                      />
                    ))}
                  </td>
                  <td>
                    <MetricLine label="vs NIFTY" value={signedPercent(feature.relative_strength.versus_nifty_percent)} valueClass={tone(feature.relative_strength.versus_nifty_percent)} />
                    <MetricLine label="vs sector" value={signedPercent(feature.relative_strength.versus_sector_percent)} valueClass={tone(feature.relative_strength.versus_sector_percent)} />
                    <MetricLine label="Pilot rank" value={feature.relative_strength.universe_percentile == null ? "N/A" : `${number(feature.relative_strength.universe_percentile, 0)} pct`} />
                  </td>
                  <td>
                    <MetricLine label="1 / 5m" value={`${signedPercent(feature.momentum.return_1m_percent)} / ${signedPercent(feature.momentum.return_5m_percent)}`} />
                    <MetricLine label="15 / 30m" value={`${signedPercent(feature.momentum.return_15m_percent)} / ${signedPercent(feature.momentum.return_30m_percent)}`} />
                    <MetricLine label="15m efficiency" value={ratio(feature.momentum.efficiency_ratio_15m)} />
                    <small className="factor-state">{feature.momentum.state.replaceAll("_", " ")}</small>
                  </td>
                  <td>
                    <MetricLine label="RVOL" value={multiple(feature.volume.relative_volume)} />
                    <MetricLine label="Acceleration" value={multiple(feature.volume.acceleration_ratio)} />
                    <MetricLine label="Last minute" value={integer(feature.volume.completed_minute_volume)} />
                    <small className="factor-state">{feature.volume.state.replaceAll("_", " ")}</small>
                  </td>
                  <td>
                    <MetricLine label="From extreme" value={percent(feature.pullback.distance_from_extreme_percent)} />
                    <MetricLine label="Recovery" value={feature.pullback.recovery_fraction == null ? "N/A" : `${number(feature.pullback.recovery_fraction * 100)}%`} />
                    <MetricLine label="Counter vol" value={multiple(feature.pullback.countertrend_volume_ratio)} />
                    <small className="factor-state">{feature.pullback.quality.replaceAll("_", " ")}</small>
                  </td>
                  <td>
                    <MetricLine label={`ATR (${feature.volatility.atr_sessions})`} value={feature.volatility.atr == null ? "N/A" : number(feature.volatility.atr)} />
                    <MetricLine label="ATR %" value={percent(feature.volatility.atr_percent)} />
                    <MetricLine label="Range / ATR" value={multiple(feature.volatility.session_range_atr)} />
                    <small className="factor-state">{feature.volatility.state}</small>
                  </td>
                  <td>
                    <MetricLine label="Spread" value={feature.liquidity.spread_bps == null ? "N/A" : `${number(feature.liquidity.spread_bps)} bps`} />
                    <MetricLine label="Traded value" value={tradedValue(feature.liquidity.total_traded_value_inr)} />
                    <MetricLine label="Depth imbalance" value={ratio(feature.liquidity.depth_imbalance)} valueClass={tone(feature.liquidity.depth_imbalance)} />
                    <span className={`filter-badge ${feature.liquidity.state}`}>{feature.liquidity.state}</span>
                  </td>
                </tr>
              );
            })}
            {!features.length && (
              <tr><td className="feature-empty" colSpan={10}>Waiting for a completed current-session candle. Prepare history, then start the live feed during market hours.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type AlphaMatrixDatum = {
  value: [number, number, number];
  name: string;
  instrumentKey: string;
  sector: string;
  finalScore: number;
  evidenceStrength: number;
  coverage: number;
  persistence: number;
  status: RankedOpportunity["score"]["status"];
  sessionReturn: number | null;
  participationScore: number | null;
  liquidityScore: number | null;
};

const MATRIX_STATUS_COLORS: Record<RankedOpportunity["score"]["status"], string> = {
  high_priority: "#61d3a4",
  promising: "#76a9ff",
  watch: "#e4c87e",
  low_conviction: "#a0aebe",
  ineligible: "#ff7f8c",
  insufficient_data: "#8c6f9e",
};

const escapeTooltip = (value: string) => value.replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[character] ?? character));

function AlphaMatrix({ rows, onSelectStock }: { rows: RankedOpportunity[]; onSelectStock: (instrumentKey: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.EChartsType | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(containerRef.current);
    chart.on("click", (params) => {
      const datum = params.data as AlphaMatrixDatum | undefined;
      if (datum?.instrumentKey) onSelectStock(datum.instrumentKey);
    });
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [onSelectStock]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const data: AlphaMatrixDatum[] = rows.map((row) => {
      const componentByKey = Object.fromEntries(row.score.components.map((component) => [component.key, component]));
      const confidenceBeforeGates = row.score.coverage_percent * row.score.persistence_multiplier;
      const confidenceProxy = row.score.eligible ? confidenceBeforeGates : Math.min(confidenceBeforeGates, 30);
      const liquidityScore = componentByKey.liquidity_execution?.score ?? null;
      return {
        value: [row.score.final_score, Math.max(0, Math.min(100, confidenceProxy)), liquidityScore ?? 0],
        name: row.symbol,
        instrumentKey: row.instrument_key,
        sector: row.sector ?? "Sector unavailable",
        finalScore: row.score.final_score,
        evidenceStrength: row.score.evidence_score,
        coverage: row.score.coverage_percent,
        persistence: row.score.persistence_multiplier,
        status: row.score.status,
        sessionReturn: row.session_return_percent,
        participationScore: componentByKey.participation?.score ?? null,
        liquidityScore,
      };
    });

    chart.setOption({
      animationDuration: 350,
      animationDurationUpdate: 500,
      aria: { enabled: true, description: "Opportunity matrix of stock evidence strength and provisional confidence." },
      grid: { left: 66, right: 28, top: 30, bottom: 68 },
      tooltip: {
        trigger: "item",
        backgroundColor: "#111b26",
        borderColor: "#34465a",
        textStyle: { color: "#dce6f2", fontSize: 12 },
        formatter: (params: { data?: AlphaMatrixDatum }) => {
          const item = params.data;
          if (!item) return "";
          return [
            `<strong>${escapeTooltip(item.name)}</strong> · ${escapeTooltip(item.sector)}`,
            `Final opportunity score: ${item.finalScore.toFixed(1)}`,
            `Evidence strength: ${item.evidenceStrength.toFixed(1)}`,
            `Confidence proxy: ${item.value[1].toFixed(1)}`,
            `Coverage: ${item.coverage.toFixed(0)}% · persistence ${item.persistence.toFixed(2)}x`,
            `Liquidity score: ${item.liquidityScore == null ? "N/A" : item.liquidityScore.toFixed(0)}`,
            `Participation score: ${item.participationScore == null ? "N/A" : item.participationScore.toFixed(0)}`,
            `Session: ${item.sessionReturn == null ? "N/A" : `${item.sessionReturn > 0 ? "+" : ""}${item.sessionReturn.toFixed(2)}%`}`,
            `<span style="color:#91a0b5">Click for the consolidated stock view</span>`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "OPPORTUNITY SCORE →",
        nameLocation: "middle",
        nameGap: 42,
        nameTextStyle: { color: "#8291a5", fontSize: 11, fontWeight: 700 },
        axisLabel: { color: "#718095" },
        axisLine: { lineStyle: { color: "#344255" } },
        splitLine: { lineStyle: { color: "#202b39", type: "dashed" } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        name: "CONFIDENCE PROXY →",
        nameLocation: "middle",
        nameGap: 48,
        nameTextStyle: { color: "#8291a5", fontSize: 11, fontWeight: 700 },
        axisLabel: { color: "#718095" },
        axisLine: { show: true, lineStyle: { color: "#344255" } },
        splitLine: { lineStyle: { color: "#202b39", type: "dashed" } },
      },
      series: [{
        type: "scatter",
        data: data.map((item) => ({
          ...item,
          symbol: item.status === "ineligible" || item.status === "insufficient_data" ? "diamond" : "circle",
          itemStyle: { color: MATRIX_STATUS_COLORS[item.status], borderColor: "#dce6f2", borderWidth: 1, opacity: .88 },
          label: { show: true, formatter: item.name, position: "top", color: "#d7e1ed", fontSize: 9, fontWeight: 700 },
        })),
        symbolSize: (value: number[]) => 11 + Math.max(0, Math.min(100, value[2] ?? 20)) * .25,
        emphasis: { focus: "self", scale: 1.3, label: { show: true, color: "#ffffff", fontSize: 11 } },
        labelLayout: { hideOverlap: true },
        markArea: {
          silent: true,
          label: { color: "#8291a5", fontSize: 10, fontWeight: 700 },
          data: [
            [{ name: "AVOID / INCOMPLETE", xAxis: 0, yAxis: 0, itemStyle: { color: "rgba(255,127,140,.045)" } }, { xAxis: 70, yAxis: 65 }],
            [{ name: "RELIABLE · LOWER SCORE", xAxis: 0, yAxis: 65, itemStyle: { color: "rgba(118,169,255,.045)" } }, { xAxis: 70, yAxis: 100 }],
            [{ name: "EMERGING · NEEDS CONFIRMATION", xAxis: 70, yAxis: 0, itemStyle: { color: "rgba(228,200,126,.055)" } }, { xAxis: 100, yAxis: 65 }],
            [{ name: "STRONG OPPORTUNITY", xAxis: 70, yAxis: 65, itemStyle: { color: "rgba(97,211,164,.065)" } }, { xAxis: 100, yAxis: 100 }],
          ],
        },
      }],
    }, { notMerge: true });
  }, [rows]);

  return (
    <div className="alpha-matrix-shell">
      <div className="alpha-matrix-heading">
        <div><h3>Alpha Matrix</h3><p>Opportunity Score versus a provisional coverage-and-persistence confidence proxy</p></div>
        <div className="alpha-matrix-legend" aria-label="Opportunity status colours">
          {Object.entries(MATRIX_STATUS_COLORS).map(([status, color]) => <span key={status}><i style={{ background: color }} />{status.replaceAll("_", " ")}</span>)}
        </div>
      </div>
      <div className="alpha-matrix-chart" ref={containerRef} role="img" aria-label="Interactive Alpha Matrix. Select a stock bubble to open its detailed view." />
      {!rows.length && <p className="alpha-matrix-empty">Waiting for completed-minute opportunities.</p>}
      <p className="alpha-matrix-note">Bubble size represents liquidity/execution score. Ineligible stocks are pulled into the low-confidence region. Axes and quadrant boundaries are provisional until backtested.</p>
    </div>
  );
}

function OpportunityRankingBoard({ rows, onSelectStock }: { rows: RankedOpportunity[]; onSelectStock: (instrumentKey: string) => void }) {
  const componentKeys = ["price_trend", "participation", "market_sector", "liquidity_execution", "fundamental", "catalyst"];
  return (
    <section className="table-card opportunity-card">
      <div className="table-heading">
        <div><h2>Explainable opportunity ranking</h2><p>Coverage-adjusted long-continuation candidates, recalculated every completed minute</p></div>
        <span>Pilot v1 · provisional weights · not yet backtested</span>
      </div>
      <AlphaMatrix rows={rows} onSelectStock={onSelectStock} />
      <div className="table-scroll">
        <table className="opportunity-table">
          <thead><tr><th>Rank</th><th>Stock</th><th>CMP</th><th>Opportunity score</th>{componentKeys.map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}<th>Why it ranks</th><th>Risk / missing</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const components = Object.fromEntries(row.score.components.map((component) => [component.key, component]));
              return (
                <tr key={row.instrument_key}>
                  <td className="rank-cell">{row.rank ?? "—"}</td>
                  <td>
                    <button className="stock-detail-link" type="button" onClick={() => onSelectStock(row.instrument_key)}>
                      <strong>{row.symbol}</strong><small>View details →</small>
                    </button>
                    <small>{row.sector ?? "Sector unavailable"}</small>
                    <span className={`score-status ${row.score.status}`}>{row.score.status.replaceAll("_", " ")}</span>
                  </td>
                  <td className="numeric cmp-cell"><strong className={`cmp-price ${tone(row.session_return_percent)}`}>{row.current_market_price == null ? "—" : `₹${number(row.current_market_price)}`}</strong><span className={`cmp-change ${tone(row.session_return_percent)}`}>{signedPercent(row.session_return_percent)}</span><small>Current market session</small></td>
                  <td><strong className="opportunity-score">{number(row.score.final_score, 1)}</strong><small>Evidence {number(row.score.evidence_score, 1)} · coverage {number(row.score.coverage_percent, 0)}%</small><small>Persistence ×{number(row.score.persistence_multiplier, 2)}</small></td>
                  {componentKeys.map((key) => {
                    const component = components[key];
                    return <td key={key}>{component ? <><strong>{component.score == null ? "N/A" : number(component.score, 0)}</strong><small>{number(component.weight_percent, 0)}% weight · {number(component.coverage_percent, 0)}% covered</small><small>{number(component.contribution_points, 1)} points</small></> : "N/A"}</td>;
                  })}
                  <td className="tag-cell">{row.score.top_positive_factors.slice(0, 4).map((item) => <span className="evidence-tag" key={item}>{item.replaceAll("_", " ")}</span>)}{!row.score.top_positive_factors.length && <span className="factor-state">No strong positive evidence</span>}</td>
                  <td className="tag-cell">{[...row.score.invalidation_reasons, ...row.score.top_cautions].slice(0, 5).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}{!row.score.invalidation_reasons.length && !row.score.top_cautions.length && <span className="evidence-tag">No active caution</span>}</td>
                </tr>
              );
            })}
            {!rows.length && <tr><td className="feature-empty" colSpan={12}>Waiting for completed-minute evidence and risk checks before ranking opportunities.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EvidenceBoard({ rows }: { rows: OpportunityEvidence[] }) {
  return (
    <section className="table-card evidence-card">
      <div className="table-heading">
        <div><h2>Validated evidence confluence</h2><p>Intraday, daily, market-relative, volume and liquidity evidence in one view</p></div>
        <span>Underlying evidence used by the provisional ranking model</span>
      </div>
      <div className="table-scroll">
        <table className="evidence-table">
          <thead><tr><th>Stock</th><th>Confluence</th><th>Persistence</th><th>Risk gates</th><th>Intraday</th><th>Daily regime</th><th>NIFTY / sector</th><th>Volume / liquidity</th><th>Corporate event</th><th>Validation</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const pillars = Object.fromEntries(row.pillars.map((pillar) => [pillar.key, pillar]));
              return (
                <tr key={row.instrument_key}>
                  <td><strong>{row.symbol}</strong><small>{row.sector ?? "Sector unavailable"}</small><span className={`quality-badge ${row.data_quality}`}>{row.data_quality}</span></td>
                  <td><span className={`confluence-badge ${row.confluence}`}>{row.confluence.replaceAll("_", " ")}</span></td>
                  <td>{row.signal_persistence ? <><span className={`signal-badge ${row.signal_persistence.state}`}>{row.signal_persistence.state}</span><small>{row.signal_persistence.supportive_minutes}/{row.signal_persistence.observed_minutes} supportive minutes</small>{row.signal_persistence.transition && <span className="evidence-tag">{row.signal_persistence.transition.replaceAll("_", " ")}</span>}</> : "N/A"}</td>
                  <td>{row.risk_assessment ? <><span className={`filter-badge ${row.risk_assessment.status === "rejected" ? "reject" : row.risk_assessment.status}`}>{row.risk_assessment.status}</span><MetricLine label="Buy slip" value={row.risk_assessment.estimated_buy_slippage_bps == null ? "N/A" : `${number(row.risk_assessment.estimated_buy_slippage_bps)} bps`} /><MetricLine label="Upper circuit" value={percent(row.risk_assessment.distance_to_upper_circuit_percent)} />{row.risk_assessment.gates.filter((gate) => gate.status !== "pass").slice(0, 2).map((gate) => <span className="caution-tag" key={gate.key}>{gate.key.replaceAll("_", " ")}: {gate.status}</span>)}</> : "N/A"}</td>
                  {(["intraday", "daily", "relative_strength", "confirmation"] as const).map((key) => {
                    const pillar = pillars[key];
                    if (key === "confirmation") {
                      const flow = row.flow_liquidity;
                      return (
                        <td key={key}>
                          <span className={`confirmation-badge ${flow.confirmation}`}>{flow.confirmation.replaceAll("_", " ")}</span>
                          <MetricLine label="RVOL" value={multiple(flow.relative_volume)} />
                          <MetricLine label="Acceleration" value={multiple(flow.volume_acceleration)} />
                          <MetricLine label="Spread" value={flow.spread_bps == null ? "N/A" : `${number(flow.spread_bps)} bps`} />
                          <MetricLine label="Traded value" value={tradedValue(flow.traded_value_inr)} />
                          <small>{flow.volume_state.replaceAll("_", " ")} volume · {flow.liquidity_state.replaceAll("_", " ")} liquidity</small>
                          {flow.cautions.slice(0, 2).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
                        </td>
                      );
                    }
                    return <td key={key}>{pillar ? <><span className={`pillar-state ${pillar.state}`}>{pillar.state}</span><small>{pillar.supportive_checks} supportive · {pillar.caution_checks} cautions</small>{pillar.evidence.slice(0, 2).map((item) => <span className="evidence-tag" key={item}>{item.replaceAll("_", " ")}</span>)}{pillar.cautions.slice(0, 2).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}</> : "N/A"}</td>;
                  })}
                  <td>{row.corporate_action_context ? <><span className={`pillar-state ${row.corporate_action_context.state === "positive" ? "supportive" : row.corporate_action_context.state === "negative" ? "caution" : "mixed"}`}>{row.corporate_action_context.state}</span><MetricLine label="Active events" value={String(row.corporate_action_context.active_events)} /><MetricLine label="Effective score" value={row.corporate_action_context.effective_score == null ? "N/A" : number(row.corporate_action_context.effective_score, 0)} />{row.corporate_action_context.cautions.map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}</> : "N/A"}</td>
                  <td>{row.validation_notes.length ? row.validation_notes.map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>) : <span className="evidence-tag">inputs current</span>}</td>
                </tr>
              );
            })}
            {!rows.length && <tr><td className="feature-empty" colSpan={10}>Waiting for current-session feature evidence.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CorporateActionPanel({ rows, analyses }: { rows: CorporateActionAssessment[]; analyses: CorporateActionAIAnalysis[] }) {
  const aiByEvent = Object.fromEntries(analyses.map((item) => [item.event_id, item]));
  return (
    <section className="table-card corporate-action-card">
      <div className="table-heading">
        <div><h2>Corporate-action materiality</h2><p>Deterministic event metrics based on facts and the pre-event close</p></div>
        <span>Versioned rules · AI is optional and source-grounded</span>
      </div>
      <div className="table-scroll">
        <table className="corporate-action-table">
          <thead><tr><th>Stock</th><th>Action</th><th>Direction</th><th>Materiality</th><th>Sentiment</th><th>Derived metrics</th><th>Confidence</th><th>Grounded AI</th><th>Review notes</th></tr></thead>
          <tbody>{rows.map((row) => {
            const ai = aiByEvent[row.event_id];
            return <tr key={`${row.event_id}-${row.assessment_version}`}>
              <td><strong>{row.symbol}</strong><small>{row.reference_price_date ? `Reference ${row.reference_price_date}` : "Reference price unavailable"}</small></td>
              <td><span className="factor-state">{row.category}</span><small>{row.impact_horizon.replaceAll("_", " ")}</small></td>
              <td><span className={`direction-badge ${row.direction}`}>{row.direction}</span></td>
              <td className="numeric"><strong>{number(row.materiality_score, 0)}/100</strong></td>
              <td className={`numeric ${tone(row.sentiment_score)}`}>{row.sentiment_score > 0 ? "+" : ""}{number(row.sentiment_score, 0)}</td>
              <td>{Object.entries(row.derived_metrics).slice(0, 4).map(([key, value]) => <MetricLine key={key} label={key.replaceAll("_", " ")} value={typeof value === "number" ? number(value) : value ?? "N/A"} />)}</td>
              <td><strong>{number(row.confidence * 100, 0)}%</strong><small>Rules v{row.assessment_version}</small></td>
              <td>{ai?.grounded ? <><strong className={tone(ai.impact_score)}>{ai.impact_score != null && ai.impact_score > 0 ? "+" : ""}{number(ai.impact_score, 0)}</strong><small>{number((ai.confidence ?? 0) * 100, 0)}% confidence · {ai.citation_document_ids.length} citation(s)</small>{ai.rationale && <span className="evidence-tag">{ai.rationale}</span>}</> : <><span className="factor-state">Not active</span><small>{ai?.error?.replaceAll("_", " ") ?? "No eligible grounded analysis"}</small></>}</td>
              <td>{row.cautions.slice(0, 3).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}{!row.requires_ai_review && <span className="evidence-tag">rules sufficient</span>}</td>
            </tr>;
          })}</tbody>
          {!rows.length && <tbody><tr><td className="feature-empty" colSpan={9}>No corporate-action materiality records are available for the pilot stocks.</td></tr></tbody>}
        </table>
      </div>
    </section>
  );
}

function ApprovedStocksPanel({ stocks }: { stocks: WatchlistItem[] }) {
  return (
    <section className="table-card">
      <div className="table-heading">
        <div><h2>Approved stocks</h2><p>Latest available one-minute values</p></div>
        <span>Refreshes every 5 seconds · calculations every 60 seconds</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Stock</th><th>Sector</th><th>LTP</th><th>Change</th><th>1m O / H / L / C</th><th>Volume</th><th>RVOL</th><th>Spread</th><th>State</th></tr></thead>
          <tbody>
            {stocks.map((stock) => (
              <tr key={stock.instrument_key}>
                <td><strong>{stock.symbol}</strong><small>{stock.company_name}</small></td>
                <td>{stock.sector ?? "—"}</td>
                <td className="numeric">{number(stock.ltp)}</td>
                <td className={`numeric ${(stock.change_percent ?? 0) > 0 ? "positive" : (stock.change_percent ?? 0) < 0 ? "negative" : ""}`}>
                  {stock.change_percent == null ? "—" : `${stock.change_percent > 0 ? "+" : ""}${number(stock.change_percent)}%`}
                </td>
                <td className="numeric candle-values">{[stock.open, stock.high, stock.low, stock.close].map((value) => number(value)).join(" / ")}</td>
                <td className="numeric">{integer(stock.volume)}</td>
                <td className="numeric" title={stock.relative_volume == null ? "No current-session comparable RVOL is available yet" : "Relative volume for the latest completed one-minute candle"}>
                  {stock.relative_volume == null ? "N/A" : `${number(stock.relative_volume)}x`}
                </td>
                <td className="numeric">{stock.spread_bps == null ? "—" : `${number(stock.spread_bps)} bps`}</td>
                <td><span className={`data-badge ${stock.data_state}`}>{stock.data_state}</span></td>
              </tr>
            ))}
            {!stocks.length && <tr><td className="feature-empty" colSpan={9}>Waiting for approved-stock market data.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FinancialsPanel({ rows }: { rows: FinancialMetricSnapshot[] }) {
  const crore = (value: number | null) => value == null ? "N/A" : `Rs ${number(value)} cr`;
  const points = (value: number | null) => value == null ? "N/A" : `${value > 0 ? "+" : ""}${number(value)} pp`;

  return (
    <section className="table-card financials-card">
      <div className="table-heading">
        <div><h2>Financials (Quarterly / Yearly)</h2><p>Latest stored statement-derived metrics for each pilot stock</p></div>
        <span>Versioned Upstox snapshots · missing values remain N/A</span>
      </div>
      <div className="table-scroll">
        <table className="financials-table">
          <thead>
            <tr><th>Stock / reporting</th><th>Revenue growth</th><th>Operating profit</th><th>Net profit</th><th>Margins</th><th>Cash / balance sheet</th><th>Returns</th><th>EPS trend</th><th>Coverage notes</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.source_snapshot_id}-${row.calculation_version}`}>
                <td>
                  <strong>{row.symbol}</strong>
                  <MetricLine label="Latest quarter" value={row.latest_quarter ?? "N/A"} />
                  <MetricLine label="Latest annual" value={row.latest_annual_period ?? "N/A"} />
                  <span className={`quality-badge ${row.data_quality}`}>{row.data_quality}</span>
                </td>
                <td>
                  <MetricLine label="QoQ" value={signedPercent(row.growth.revenue_qoq_percent)} valueClass={tone(row.growth.revenue_qoq_percent)} />
                  <MetricLine label="YoY" value={signedPercent(row.growth.revenue_yoy_percent)} valueClass={tone(row.growth.revenue_yoy_percent)} />
                </td>
                <td>
                  <MetricLine label="QoQ" value={signedPercent(row.growth.operating_profit_qoq_percent)} valueClass={tone(row.growth.operating_profit_qoq_percent)} />
                  <MetricLine label="YoY" value={signedPercent(row.growth.operating_profit_yoy_percent)} valueClass={tone(row.growth.operating_profit_yoy_percent)} />
                </td>
                <td>
                  <MetricLine label="QoQ" value={signedPercent(row.growth.net_profit_qoq_percent)} valueClass={tone(row.growth.net_profit_qoq_percent)} />
                  <MetricLine label="YoY" value={signedPercent(row.growth.net_profit_yoy_percent)} valueClass={tone(row.growth.net_profit_yoy_percent)} />
                </td>
                <td>
                  <MetricLine label="Operating" value={percent(row.margins.operating_margin_percent)} />
                  <MetricLine label="Op QoQ / YoY" value={`${points(row.margins.operating_margin_qoq_change_pp)} / ${points(row.margins.operating_margin_yoy_change_pp)}`} />
                  <MetricLine label="Net" value={percent(row.margins.net_margin_percent)} />
                  <MetricLine label="Net QoQ / YoY" value={`${points(row.margins.net_margin_qoq_change_pp)} / ${points(row.margins.net_margin_yoy_change_pp)}`} />
                </td>
                <td>
                  <MetricLine label="Cash conversion" value={percent(row.capital.operating_cash_conversion_percent)} />
                  <MetricLine label="Debt" value={crore(row.capital.total_debt_crore)} />
                  <MetricLine label="Debt YoY" value={signedPercent(row.capital.debt_yoy_change_percent)} valueClass={tone(row.capital.debt_yoy_change_percent == null ? null : -row.capital.debt_yoy_change_percent)} />
                  <MetricLine label="Debt / equity" value={ratio(row.capital.debt_to_equity)} />
                  <MetricLine label="Liabilities" value={crore(row.capital.total_liabilities_crore)} />
                  <MetricLine label="Liabilities YoY" value={signedPercent(row.capital.liabilities_yoy_change_percent)} valueClass={tone(row.capital.liabilities_yoy_change_percent == null ? null : -row.capital.liabilities_yoy_change_percent)} />
                </td>
                <td>
                  <MetricLine label="ROE" value={percent(row.capital.roe_percent)} />
                  <MetricLine label="ROCE" value={percent(row.capital.roce_percent)} />
                </td>
                <td>
                  <MetricLine label={`Basic EPS${row.eps.latest_period ? ` · ${row.eps.latest_period}` : ""}`} value={row.eps.latest_basic_eps == null ? "N/A" : number(row.eps.latest_basic_eps)} />
                  <MetricLine label="EPS YoY" value={signedPercent(row.eps.yoy_growth_percent)} valueClass={tone(row.eps.yoy_growth_percent)} />
                  {row.eps.history.length > 0 && <small className="financial-history">{row.eps.history.slice(0, 5).map((item) => `${item.period}: ${typeof item.value === "number" ? number(item.value) : item.value}`).join(" · ")}</small>}
                </td>
                <td className="tag-cell">
                  <MetricLine label="Calculated" value={new Date(row.calculated_at).toLocaleDateString("en-IN")} />
                  <MetricLine label="Unavailable" value={String(row.unavailable.length)} />
                  {row.unavailable.slice(0, 3).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
                  {row.cautions.slice(0, 2).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
                  {!row.unavailable.length && !row.cautions.length && <span className="evidence-tag">complete inputs</span>}
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td className="feature-empty" colSpan={9}>No stored financial metrics are available. Use Prepare stocks or Check financial results to populate them.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DetailCard({ title, subtitle, children, wide = false }: { title: string; subtitle?: string; children: ReactNode; wide?: boolean }) {
  return (
    <article className={`stock-detail-card ${wide ? "wide" : ""}`}>
      <div className="stock-detail-card-heading"><h3>{title}</h3>{subtitle && <span>{subtitle}</span>}</div>
      <div className="stock-detail-card-body">{children}</div>
    </article>
  );
}

type StockDetailPanelProps = {
  instrumentKey: string;
  stocks: WatchlistItem[];
  opportunities: RankedOpportunity[];
  features: StockFeatures[];
  regimes: DailyRegime[];
  evidenceRows: OpportunityEvidence[];
  financialRows: FinancialMetricSnapshot[];
  corporateRows: CorporateActionAssessment[];
  corporateAI: CorporateActionAIAnalysis[];
  context: MarketContext | null;
  onBack: () => void;
};

function StockDetailPanel({ instrumentKey, stocks, opportunities, features, regimes, evidenceRows, financialRows, corporateRows, corporateAI, context, onBack }: StockDetailPanelProps) {
  const stock = stocks.find((item) => item.instrument_key === instrumentKey);
  const opportunity = opportunities.find((item) => item.instrument_key === instrumentKey);
  const feature = features.find((item) => item.instrument_key === instrumentKey);
  const regime = regimes.find((item) => item.instrument_key === instrumentKey);
  const evidence = evidenceRows.find((item) => item.instrument_key === instrumentKey);
  const financial = financialRows.find((item) => item.instrument_key === instrumentKey);
  const actions = corporateRows.filter((item) => item.instrument_key === instrumentKey);
  const aiByEvent = Object.fromEntries(corporateAI.map((item) => [item.event_id, item]));
  const symbol = opportunity?.symbol ?? stock?.symbol ?? feature?.symbol ?? regime?.symbol ?? "Selected stock";
  const sector = opportunity?.sector ?? stock?.sector ?? feature?.sector ?? regime?.sector;

  return (
    <section className="stock-detail-shell">
      <div className="stock-detail-header">
        <div>
          <p className="eyebrow">CONSOLIDATED STOCK VIEW</p>
          <h2>{symbol}</h2>
          <p>{sector ?? "Sector unavailable"} · information combined from every Q-FAE evidence section</p>
        </div>
        <button className="secondary" type="button" onClick={onBack}>← Back to ranking</button>
      </div>

      <div className="stock-detail-grid">
        <DetailCard title="Market snapshot" subtitle={stock?.data_state ?? "waiting"}>
          <div className="detail-hero-metric">
            <strong className={tone(stock?.change_percent ?? opportunity?.session_return_percent ?? null)}>{stock?.ltp == null ? opportunity?.current_market_price == null ? "N/A" : `₹${number(opportunity.current_market_price)}` : `₹${number(stock.ltp)}`}</strong>
            <span className={tone(stock?.change_percent ?? opportunity?.session_return_percent ?? null)}>{signedPercent(stock?.change_percent ?? opportunity?.session_return_percent ?? null)}</span>
          </div>
          <MetricLine label="Open" value={stock?.open == null ? "N/A" : number(stock.open)} />
          <MetricLine label="High / low" value={`${stock?.high == null ? "N/A" : number(stock.high)} / ${stock?.low == null ? "N/A" : number(stock.low)}`} />
          <MetricLine label="Latest minute volume" value={integer(stock?.volume ?? null)} />
          <MetricLine label="Updated" value={stock?.updated_at ? new Date(stock.updated_at).toLocaleTimeString("en-IN") : "N/A"} />
        </DetailCard>

        <DetailCard title="Opportunity ranking" subtitle={opportunity ? `Rank ${opportunity.rank ?? "—"}` : "Not ranked"}>
          {opportunity ? <>
            <div className="detail-score-row"><strong>{number(opportunity.score.final_score, 1)}</strong><span className={`score-status ${opportunity.score.status}`}>{opportunity.score.status.replaceAll("_", " ")}</span></div>
            <MetricLine label="Evidence score" value={number(opportunity.score.evidence_score, 1)} />
            <MetricLine label="Coverage" value={`${number(opportunity.score.coverage_percent, 0)}%`} />
            <MetricLine label="Persistence" value={`${number(opportunity.score.persistence_multiplier, 2)}x`} />
            <MetricLine label="Eligible" value={opportunity.score.eligible ? "Yes" : "No"} />
          </> : <p className="detail-empty">No current opportunity score.</p>}
        </DetailCard>

        <DetailCard title="Market context" subtitle={context ? new Date(context.as_of).toLocaleTimeString("en-IN") : "Unavailable"}>
          <MetricLine label="NIFTY 50" value={context?.nifty_50.ltp == null ? "N/A" : number(context.nifty_50.ltp)} />
          <MetricLine label="NIFTY change" value={signedPercent(context?.nifty_50.change_percent ?? null)} valueClass={tone(context?.nifty_50.change_percent ?? null)} />
          <MetricLine label="India VIX" value={context?.india_vix.ltp == null ? "N/A" : number(context.india_vix.ltp)} />
          <MetricLine label="Advance / decline" value={`${context?.advancers ?? 0} / ${context?.decliners ?? 0}`} />
          <MetricLine label="Median spread" value={context?.median_spread_bps == null ? "N/A" : `${number(context.median_spread_bps)} bps`} />
        </DetailCard>

        <DetailCard title="VWAP, gap and opening ranges" subtitle={feature?.data_quality ?? "Unavailable"}>
          {feature ? <>
            <MetricLine label="VWAP position" value={signedPercent(feature.vwap.position_percent)} valueClass={tone(feature.vwap.position_percent)} />
            <MetricLine label="VWAP 5m slope/min" value={signedPercent(feature.vwap.slope_5m_percent_per_minute)} valueClass={tone(feature.vwap.slope_5m_percent_per_minute)} />
            <MetricLine label="Opening gap" value={signedPercent(feature.gap.gap_percent)} valueClass={tone(feature.gap.gap_percent)} />
            <MetricLine label="Gap retention" value={signedPercent(feature.gap.retention_percent)} valueClass={tone(feature.gap.retention_percent)} />
            <div className="detail-range-list">{feature.opening_ranges.map((range) => <span key={range.minutes}><b>{range.minutes}m</b>{range.ready ? `${range.position} · ${signedPercent(range.breakout_percent)}` : "forming"}</span>)}</div>
          </> : <p className="detail-empty">Intraday features will appear after a completed market minute.</p>}
        </DetailCard>

        <DetailCard title="Momentum and relative strength" subtitle={feature?.momentum.state.replaceAll("_", " ")}>
          {feature ? <>
            <MetricLine label="1m / 5m return" value={`${signedPercent(feature.momentum.return_1m_percent)} / ${signedPercent(feature.momentum.return_5m_percent)}`} />
            <MetricLine label="15m / 30m return" value={`${signedPercent(feature.momentum.return_15m_percent)} / ${signedPercent(feature.momentum.return_30m_percent)}`} />
            <MetricLine label="15m efficiency" value={ratio(feature.momentum.efficiency_ratio_15m)} />
            <MetricLine label="Bullish candles (10m)" value={percent(feature.momentum.bullish_candle_ratio_10m == null ? null : feature.momentum.bullish_candle_ratio_10m * 100)} />
            <MetricLine label="Versus NIFTY" value={signedPercent(feature.relative_strength.versus_nifty_percent)} valueClass={tone(feature.relative_strength.versus_nifty_percent)} />
            <MetricLine label="Versus sector" value={signedPercent(feature.relative_strength.versus_sector_percent)} valueClass={tone(feature.relative_strength.versus_sector_percent)} />
            <MetricLine label="Pilot percentile" value={feature.relative_strength.universe_percentile == null ? "N/A" : `${number(feature.relative_strength.universe_percentile, 0)} pct`} />
          </> : <p className="detail-empty">No current-session momentum evidence.</p>}
        </DetailCard>

        <DetailCard title="Volume and liquidity" subtitle={evidence?.flow_liquidity.confirmation.replaceAll("_", " ") ?? feature?.liquidity.state ?? "Unavailable"}>
          <MetricLine label="Intraday RVOL" value={multiple(feature?.volume.relative_volume ?? stock?.relative_volume ?? null)} />
          <MetricLine label="Volume acceleration" value={multiple(feature?.volume.acceleration_ratio ?? null)} />
          <MetricLine label="Traded value" value={tradedValue(feature?.liquidity.total_traded_value_inr ?? null)} />
          <MetricLine label="Spread" value={(feature?.liquidity.spread_bps ?? stock?.spread_bps) == null ? "N/A" : `${number((feature?.liquidity.spread_bps ?? stock?.spread_bps) as number)} bps`} />
          <MetricLine label="Depth imbalance" value={ratio(feature?.liquidity.depth_imbalance ?? null)} valueClass={tone(feature?.liquidity.depth_imbalance ?? null)} />
          <MetricLine label="Spread filter" value={feature?.liquidity.passes_spread_filter == null ? "N/A" : feature.liquidity.passes_spread_filter ? "Pass" : "Reject"} />
          <MetricLine label="Traded-value filter" value={feature?.liquidity.passes_traded_value_filter == null ? "N/A" : feature.liquidity.passes_traded_value_filter ? "Pass" : "Reject"} />
        </DetailCard>

        <DetailCard title="Daily trend and structure" subtitle={regime ? `${regime.sessions_available} sessions · ${regime.trend.regime.replaceAll("_", " ")}` : "Unavailable"} wide>
          {regime ? <div className="detail-two-column">
            <div>
              <MetricLine label="Versus SMA20" value={signedPercent(regime.trend.above_sma_20_percent)} valueClass={tone(regime.trend.above_sma_20_percent)} />
              <MetricLine label="Versus SMA50" value={signedPercent(regime.trend.above_sma_50_percent)} valueClass={tone(regime.trend.above_sma_50_percent)} />
              <MetricLine label="SMA20 slope (5d)" value={signedPercent(regime.trend.sma_20_slope_5d_percent)} valueClass={tone(regime.trend.sma_20_slope_5d_percent)} />
              <MetricLine label="SMA50 slope (10d)" value={signedPercent(regime.trend.sma_50_slope_10d_percent)} valueClass={tone(regime.trend.sma_50_slope_10d_percent)} />
              <MetricLine label="From 252d high" value={signedPercent(regime.structure.drawdown_from_252d_high_percent)} />
              <MetricLine label="Daily RVOL" value={multiple(regime.participation.relative_volume)} />
              <MetricLine label="ATR14" value={percent(regime.volatility.atr_14_percent)} />
            </div>
            <div className="detail-horizons">{regime.horizon_performance.map((horizon) => <span key={horizon.sessions}><b>{horizon.sessions} sessions</b><strong className={tone(horizon.stock_return_percent)}>{signedPercent(horizon.stock_return_percent)}</strong><small className={tone(horizon.versus_nifty_percent)}>vs NIFTY {signedPercent(horizon.versus_nifty_percent)}</small><small className={tone(horizon.versus_sector_percent)}>vs sector {signedPercent(horizon.versus_sector_percent)}</small></span>)}</div>
          </div> : <p className="detail-empty">Prepare daily history to calculate the stock regime.</p>}
        </DetailCard>

        <DetailCard title="Evidence, persistence and risk" subtitle={evidence?.confluence.replaceAll("_", " ") ?? "Unavailable"} wide>
          {evidence ? <>
            <div className="detail-pillar-grid">{evidence.pillars.map((pillar) => <div key={pillar.key}><span className={`pillar-state ${pillar.state}`}>{pillar.label}</span><small>{pillar.supportive_checks} supportive · {pillar.caution_checks} cautions</small></div>)}</div>
            <div className="detail-two-column detail-tag-groups">
              <div><h4>Positive evidence</h4>{evidence.pillars.flatMap((pillar) => pillar.evidence).slice(0, 8).map((item, index) => <span className="evidence-tag" key={`${item}-${index}`}>{item.replaceAll("_", " ")}</span>)}</div>
              <div><h4>Risk and cautions</h4>{[...evidence.validation_notes, ...evidence.pillars.flatMap((pillar) => pillar.cautions), ...(evidence.risk_assessment?.gates.filter((gate) => gate.status !== "pass").map((gate) => `${gate.key}_${gate.status}`) ?? [])].slice(0, 8).map((item, index) => <span className="caution-tag" key={`${item}-${index}`}>{item.replaceAll("_", " ")}</span>)}</div>
            </div>
            {evidence.signal_persistence && <MetricLine label="Signal persistence" value={`${evidence.signal_persistence.state} · ${evidence.signal_persistence.supportive_minutes}/${evidence.signal_persistence.observed_minutes} supportive minutes`} />}
          </> : <p className="detail-empty">No validated confluence snapshot is available.</p>}
        </DetailCard>

        <DetailCard title="Financial growth and profitability" subtitle={financial ? `${financial.latest_quarter ?? "Quarter N/A"} · ${financial.data_quality}` : "Loading or unavailable"}>
          {financial ? <>
            <MetricLine label="Revenue QoQ / YoY" value={`${signedPercent(financial.growth.revenue_qoq_percent)} / ${signedPercent(financial.growth.revenue_yoy_percent)}`} />
            <MetricLine label="Operating profit QoQ / YoY" value={`${signedPercent(financial.growth.operating_profit_qoq_percent)} / ${signedPercent(financial.growth.operating_profit_yoy_percent)}`} />
            <MetricLine label="Net profit QoQ / YoY" value={`${signedPercent(financial.growth.net_profit_qoq_percent)} / ${signedPercent(financial.growth.net_profit_yoy_percent)}`} />
            <MetricLine label="Operating margin" value={percent(financial.margins.operating_margin_percent)} />
            <MetricLine label="Net margin" value={percent(financial.margins.net_margin_percent)} />
            <MetricLine label="EPS / EPS YoY" value={`${financial.eps.latest_basic_eps == null ? "N/A" : number(financial.eps.latest_basic_eps)} / ${signedPercent(financial.eps.yoy_growth_percent)}`} />
          </> : <p className="detail-empty">No stored financial metric snapshot for this stock.</p>}
        </DetailCard>

        <DetailCard title="Financial quality and capital" subtitle={financial?.latest_annual_period ?? "Annual period unavailable"}>
          {financial ? <>
            <MetricLine label="Cash conversion" value={percent(financial.capital.operating_cash_conversion_percent)} />
            <MetricLine label="Debt" value={financial.capital.total_debt_crore == null ? "N/A" : `Rs ${number(financial.capital.total_debt_crore)} cr`} />
            <MetricLine label="Debt / equity" value={ratio(financial.capital.debt_to_equity)} />
            <MetricLine label="Liabilities" value={financial.capital.total_liabilities_crore == null ? "N/A" : `Rs ${number(financial.capital.total_liabilities_crore)} cr`} />
            <MetricLine label="ROE / ROCE" value={`${percent(financial.capital.roe_percent)} / ${percent(financial.capital.roce_percent)}`} />
            <MetricLine label="Missing inputs" value={String(financial.unavailable.length)} />
            {financial.unavailable.slice(0, 3).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
          </> : <p className="detail-empty">Use Check financial results to populate available provider data.</p>}
        </DetailCard>

        <DetailCard title="Corporate actions and catalysts" subtitle={`${actions.length} stored assessment${actions.length === 1 ? "" : "s"}`} wide>
          {actions.length ? <div className="detail-action-list">{actions.map((action) => {
            const ai = aiByEvent[action.event_id];
            return <div key={action.event_id}>
              <span className={`direction-badge ${action.direction}`}>{action.direction}</span>
              <strong>{action.category.replaceAll("_", " ")}</strong>
              <MetricLine label="Materiality / sentiment" value={`${number(action.materiality_score, 0)} / ${action.sentiment_score > 0 ? "+" : ""}${number(action.sentiment_score, 0)}`} />
              <MetricLine label="Horizon / confidence" value={`${action.impact_horizon.replaceAll("_", " ")} / ${number(action.confidence * 100, 0)}%`} />
              {ai?.grounded && <MetricLine label="Grounded AI impact" value={ai.impact_score == null ? "N/A" : `${ai.impact_score > 0 ? "+" : ""}${number(ai.impact_score, 0)}`} valueClass={tone(ai.impact_score)} />}
              {action.evidence.slice(0, 2).map((item) => <span className="evidence-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
              {action.cautions.slice(0, 2).map((item) => <span className="caution-tag" key={item}>{item.replaceAll("_", " ")}</span>)}
            </div>;
          })}</div> : <p className="detail-empty">No active corporate-action assessment for this stock.</p>}
        </DetailCard>

        {opportunity && <DetailCard title="Why it ranks" subtitle={opportunity.score.model_version} wide>
          <div className="detail-component-grid">{opportunity.score.components.map((component) => <div key={component.key}><strong>{component.label}</strong><span>{component.score == null ? "N/A" : number(component.score, 0)}</span><small>{number(component.weight_percent, 0)}% weight · {number(component.coverage_percent, 0)}% covered · {number(component.contribution_points, 1)} points</small></div>)}</div>
          <div className="detail-two-column detail-tag-groups"><div><h4>Top positives</h4>{opportunity.score.top_positive_factors.map((item, index) => <span className="evidence-tag" key={`${item}-${index}`}>{item.replaceAll("_", " ")}</span>)}</div><div><h4>Cautions / invalidations</h4>{[...opportunity.score.invalidation_reasons, ...opportunity.score.top_cautions].map((item, index) => <span className="caution-tag" key={`${item}-${index}`}>{item.replaceAll("_", " ")}</span>)}</div></div>
        </DetailCard>}
      </div>
    </section>
  );
}

function FinancialResultsDialog({ report, onClose }: { report: FinancialResultCheckReport; onClose: () => void }) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="results-dialog" role="dialog" aria-modal="true" aria-labelledby="financial-results-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="dialog-heading">
          <div><p className="eyebrow">FINANCIAL DATA UTILITY</p><h2 id="financial-results-title">Quarterly and annual result check</h2></div>
          <button className="secondary" type="button" onClick={onClose}>Close</button>
        </div>
        <p className="dialog-summary">Fetched {report.fetched} · reused {report.reused} · unavailable {report.unavailable} · failed {report.failed}</p>
        {report.reused > 0 && <p className="cache-guard-note">Upstox was not called for {report.reused} stock(s) because the latest completed-quarter snapshot is less than {report.cache_days} days old.</p>}
        <div className="table-scroll dialog-table-scroll">
          <table className="financial-results-table">
            <thead><tr><th>Stock</th><th>Status</th><th>Quarterly</th><th>Annual</th><th>Snapshot</th><th>Reason</th></tr></thead>
            <tbody>{report.items.map((item) => (
              <tr key={item.instrument_key}>
                <td><strong>{item.symbol}</strong></td>
                <td><span className={`data-badge ${item.state}`}>{item.state}</span></td>
                <td>{item.quarterly_available ? item.quarterly_period ?? "Available" : "Not available"}</td>
                <td>{item.annual_available ? item.annual_period ?? "Available" : "Not available"}</td>
                <td>{item.snapshot_at ? new Date(item.snapshot_at).toLocaleDateString("en-IN") : "—"}</td>
                <td><small>{item.reason.replaceAll("_", " ")}</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

type AnalysisTab = "opportunities" | "stock_detail" | "intraday" | "corporate" | "evidence" | "daily" | "financials" | "stocks";

const ANALYSIS_TABS: Array<{ id: AnalysisTab; label: string }> = [
  { id: "opportunities", label: "Opportunity Ranking" },
  { id: "intraday", label: "Intraday Features" },
  { id: "corporate", label: "Corporate Actions" },
  { id: "evidence", label: "Evidence Confluence" },
  { id: "daily", label: "Daily Regime" },
  { id: "financials", label: "Financials (Qtrly/Yearly)" },
  { id: "stocks", label: "Approved Stocks" },
];

function Dashboard() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [stocks, setStocks] = useState<WatchlistItem[]>([]);
  const [context, setContext] = useState<MarketContext | null>(null);
  const [marketRegime, setMarketRegime] = useState<MarketRegime | null>(null);
  const [features, setFeatures] = useState<StockFeatures[]>([]);
  const [regimes, setRegimes] = useState<DailyRegime[]>([]);
  const [evidence, setEvidence] = useState<OpportunityEvidence[]>([]);
  const [opportunities, setOpportunities] = useState<RankedOpportunity[]>([]);
  const [corporateActions, setCorporateActions] = useState<CorporateActionAssessment[]>([]);
  const [corporateActionAI, setCorporateActionAI] = useState<CorporateActionAIAnalysis[]>([]);
  const [financialMetrics, setFinancialMetrics] = useState<FinancialMetricSnapshot[]>([]);
  const [financialResultReport, setFinancialResultReport] = useState<FinancialResultCheckReport | null>(null);
  const [selectedInstrumentKey, setSelectedInstrumentKey] = useState<string | null>(null);
  const [activeAnalysisTab, setActiveAnalysisTab] = useState<AnalysisTab>("opportunities");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [statusResponse, watchlistResponse, contextResponse, marketRegimeResponse, featuresResponse, regimesResponse, evidenceResponse, opportunitiesResponse, corporateActionsResponse, corporateActionAIResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/market/status`),
        fetch(`${apiBaseUrl}/market/watchlist`),
        fetch(`${apiBaseUrl}/market/context`),
        fetch(`${apiBaseUrl}/market/regime`),
        fetch(`${apiBaseUrl}/market/features`),
        fetch(`${apiBaseUrl}/market/daily-regimes`),
        fetch(`${apiBaseUrl}/market/evidence`),
        fetch(`${apiBaseUrl}/market/opportunities`),
        fetch(`${apiBaseUrl}/market/corporate-action-assessments?limit=100`),
        fetch(`${apiBaseUrl}/market/corporate-action-ai`),
      ]);
      if (!statusResponse.ok || !watchlistResponse.ok) throw new Error("Market service is unavailable");
      setRuntime(await statusResponse.json() as RuntimeStatus);
      setStocks(await watchlistResponse.json() as WatchlistItem[]);
      setContext(contextResponse.ok ? await contextResponse.json() as MarketContext : null);
      setMarketRegime(marketRegimeResponse.ok ? await marketRegimeResponse.json() as MarketRegime : null);
      setFeatures(featuresResponse.ok ? await featuresResponse.json() as StockFeatures[] : []);
      setRegimes(regimesResponse.ok ? await regimesResponse.json() as DailyRegime[] : []);
      setEvidence(evidenceResponse.ok ? await evidenceResponse.json() as OpportunityEvidence[] : []);
      setOpportunities(opportunitiesResponse.ok ? await opportunitiesResponse.json() as RankedOpportunity[] : []);
      setCorporateActions(corporateActionsResponse.ok ? await corporateActionsResponse.json() as CorporateActionAssessment[] : []);
      setCorporateActionAI(corporateActionAIResponse.ok ? await corporateActionAIResponse.json() as CorporateActionAIAnalysis[] : []);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load market data");
    }
  }, []);

  const loadFinancialMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/market/financial-metrics?limit=5000&latest_only=true`);
      setFinancialMetrics(response.ok ? await response.json() as FinancialMetricSnapshot[] : []);
    } catch {
      setFinancialMetrics([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (activeAnalysisTab === "financials" || activeAnalysisTab === "stock_detail") void loadFinancialMetrics();
  }, [activeAnalysisTab, loadFinancialMetrics]);

  const runAction = async (action: "bootstrap" | "live/start" | "live/stop" | "reconcile") => {
    setBusy(action);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/market/${action}`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json() as { detail?: string };
        throw new Error(payload.detail ?? "The request could not be completed");
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The request could not be completed");
    } finally {
      setBusy(null);
    }
  };

  const checkFinancialResults = async () => {
    setBusy("financial-results");
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/market/financial-results/check?limit=${runtime?.pilot_size ?? 100}`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json() as { detail?: string };
        throw new Error(payload.detail ?? "Financial results could not be checked");
      }
      setFinancialResultReport(await response.json() as FinancialResultCheckReport);
      await refresh();
      await loadFinancialMetrics();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Financial results could not be checked");
    } finally {
      setBusy(null);
    }
  };

  const bootstrapping = runtime?.bootstrap.state === "running";
  const reconciling = runtime?.reconciliation.state === "running";
  const live = runtime?.live.connected === true;
  const liveStarting = ["connecting", "reconnecting"].includes(runtime?.live.state ?? "");
  const pilotSize = runtime?.pilot_size ?? 100;
  const selectedOpportunity = opportunities.find((item) => item.instrument_key === selectedInstrumentKey);
  const analysisTabs = selectedInstrumentKey
    ? [ANALYSIS_TABS[0], { id: "stock_detail" as const, label: `${selectedOpportunity?.symbol ?? "Stock"} Detail` }, ...ANALYSIS_TABS.slice(1)]
    : ANALYSIS_TABS;

  const openStockDetail = useCallback((instrumentKey: string) => {
    setSelectedInstrumentKey(instrumentKey);
    setActiveAnalysisTab("stock_detail");
  }, []);

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <Brand />
        <div className="connection-block">
          <div className="connection-state"><span className={`state-dot ${live ? "online" : ""}`} />{live ? "Live feed connected" : `Feed ${runtime?.live.state ?? "checking"}`}</div>
          <small>Automatic stop at 3:30 PM IST</small>
        </div>
      </header>

      <section className="dashboard-intro">
        <div>
          <p className="eyebrow">{pilotSize}-STOCK PILOT</p>
          <h1>Market workspace</h1>
          <p>Daily regime evidence and live OHLCV are combined on a one-minute cadence.</p>
        </div>
        <div className="actions">
          <button className="secondary" type="button" disabled={bootstrapping || busy !== null} onClick={() => void runAction("bootstrap")}>
            {bootstrapping ? `Preparing ${runtime?.bootstrap.processed ?? 0}/${runtime?.bootstrap.total ?? pilotSize}` : `Prepare ${pilotSize} stocks`}
          </button>
          <button className="secondary" type="button" disabled={live || bootstrapping || reconciling || busy !== null || !runtime?.database_available} onClick={() => void runAction("reconcile")}>
            {reconciling ? `Reconciling ${runtime?.reconciliation.processed ?? 0}/${runtime?.reconciliation.total ?? 35}` : "Reconcile close"}
          </button>
          {!live && !liveStarting ? (
            <button type="button" disabled={busy !== null || !runtime?.redis_available} onClick={() => void runAction("live/start")}>Start live feed</button>
          ) : (
            <button className="danger-button" type="button" disabled={busy !== null} onClick={() => void runAction("live/stop")}>Stop live feed</button>
          )}
        </div>
      </section>

      {error && <p className="notice error dashboard-notice">{error}</p>}

      <section className="summary-grid" aria-label="Market data status">
        <article><span>Redis</span><strong>{runtime?.redis_available ? "Ready" : "Offline"}</strong></article>
        <article><span>PostgreSQL</span><strong>{runtime?.database_available ? "Ready" : "Offline"}</strong></article>
        <article><span>History</span><strong>{runtime?.bootstrap.history_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Minute stored</span><strong>{runtime?.bootstrap.minute_history_persisted ?? 0}/{pilotSize}</strong></article>
        <article><span>RVOL profiles</span><strong>{runtime?.bootstrap.minute_profiles_built ?? 0}/{pilotSize}</strong></article>
        <article><span>Daily regimes</span><strong>{runtime?.bootstrap.daily_history_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Daily stored</span><strong>{runtime?.bootstrap.daily_history_persisted ?? 0}/{pilotSize}</strong></article>
        <article><span>Sectors</span><strong>{runtime?.bootstrap.sectors_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Corporate actions</span><strong>{runtime?.bootstrap.corporate_actions_synced ?? 0}/{pilotSize}</strong></article>
        <article><span>CA assessments</span><strong>{runtime?.bootstrap.corporate_actions_assessed ?? 0}</strong></article>
        <article><span>CA outcomes</span><strong>{runtime?.bootstrap.corporate_outcomes_evaluated ?? 0}</strong></article>
        <article><span>CA sources</span><strong>{runtime?.bootstrap.corporate_documents_stored ?? 0}</strong></article>
        <article><span>Financial reused</span><strong>{runtime?.bootstrap.financial_results_reused ?? 0}</strong></article>
        <article><span>Subscribed</span><strong>{runtime?.live.subscribed ?? 0}</strong></article>
        <article><span>Reconciliation</span><strong>{runtime?.reconciliation.state ?? "Idle"}</strong></article>
      </section>

      <MarketContextPanel context={context} regime={marketRegime} />

      <section className="analysis-workspace" aria-label="Market analysis workspace">
        <div className="analysis-tabs" role="tablist" aria-label="Analysis sections">
          {analysisTabs.map((tab) => (
            <button
              className={`analysis-tab ${activeAnalysisTab === tab.id ? "active" : ""}`}
              id={`analysis-tab-${tab.id}`}
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeAnalysisTab === tab.id}
              aria-controls={`analysis-panel-${tab.id}`}
              tabIndex={activeAnalysisTab === tab.id ? 0 : -1}
              onClick={() => setActiveAnalysisTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="analysis-tab-panel" id={`analysis-panel-${activeAnalysisTab}`} role="tabpanel" aria-labelledby={`analysis-tab-${activeAnalysisTab}`}>
          {activeAnalysisTab === "opportunities" && <OpportunityRankingBoard rows={opportunities} onSelectStock={openStockDetail} />}
          {activeAnalysisTab === "stock_detail" && selectedInstrumentKey && (
            <StockDetailPanel
              instrumentKey={selectedInstrumentKey}
              stocks={stocks}
              opportunities={opportunities}
              features={features}
              regimes={regimes}
              evidenceRows={evidence}
              financialRows={financialMetrics}
              corporateRows={corporateActions}
              corporateAI={corporateActionAI}
              context={context}
              onBack={() => setActiveAnalysisTab("opportunities")}
            />
          )}
          {activeAnalysisTab === "intraday" && <FeatureMatrix features={features} />}
          {activeAnalysisTab === "corporate" && <CorporateActionPanel rows={corporateActions} analyses={corporateActionAI} />}
          {activeAnalysisTab === "evidence" && <EvidenceBoard rows={evidence} />}
          {activeAnalysisTab === "daily" && <DailyRegimePanel regimes={regimes} />}
          {activeAnalysisTab === "financials" && <FinancialsPanel rows={financialMetrics} />}
          {activeAnalysisTab === "stocks" && <ApprovedStocksPanel stocks={stocks} />}
        </div>
      </section>

      <section className="financial-utility-card">
        <div><p className="eyebrow">DATA UTILITIES</p><h2>Quarterly and annual results</h2><p>Check Upstox availability for the pilot stocks. Recent latest-quarter snapshots are protected from duplicate downloads for 30 days.</p></div>
        <button className="secondary" type="button" disabled={busy !== null || !runtime?.database_available} onClick={() => void checkFinancialResults()}>{busy === "financial-results" ? "Checking results…" : "Check financial results"}</button>
      </section>

      {financialResultReport && <FinancialResultsDialog report={financialResultReport} onClose={() => setFinancialResultReport(null)} />}
    </main>
  );
}

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [backendError, setBackendError] = useState(false);

  useEffect(() => {
    void fetch(`${apiBaseUrl}/auth/upstox/status`)
      .then((response) => {
        if (!response.ok) throw new Error("Backend unavailable");
        return response.json() as Promise<AuthStatus>;
      })
      .then((status) => { setAuth(status); setBackendError(false); })
      .catch(() => setBackendError(true));
  }, []);

  return auth?.authenticated ? <Dashboard /> : <LoginPage auth={auth} backendError={backendError} />;
}
