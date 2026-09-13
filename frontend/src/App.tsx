import { useCallback, useEffect, useState } from "react";

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
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="table-card regime-card">
      <div className="table-heading">
        <div><h2>Daily regime evidence</h2><p>Independent horizons reveal established trends, pullbacks and new transitions</p></div>
        <div className="table-heading-actions"><span>Long history provides context; it never blocks fresh strength</span><SectionToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} label="Daily regime evidence" /></div>
      </div>
      {expanded && <div className="table-scroll" id="daily-regime-content">
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
      </div>}
    </section>
  );
}

function SectionToggle({ expanded, onToggle, label }: { expanded: boolean; onToggle: () => void; label: string }) {
  return <button className="section-toggle" type="button" aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Expand"} ${label}`} onClick={onToggle}><span aria-hidden="true">{expanded ? "−" : "+"}</span>{expanded ? "Collapse" : "Expand"}</button>;
}

function FeatureMatrix({ features }: { features: StockFeatures[] }) {
  const [expanded, setExpanded] = useState(true);
  const openingRange = (feature: StockFeatures, minutes: number) =>
    feature.opening_ranges.find((range) => range.minutes === minutes);

  return (
    <section className="table-card feature-card">
      <div className="table-heading">
        <div><h2>Intraday feature matrix</h2><p>Nine explainable factor groups, recalculated after every completed minute</p></div>
        <div className="table-heading-actions"><span>Raw factor detail behind the pilot opportunity score</span><SectionToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} label="Intraday feature matrix" /></div>
      </div>
      {expanded && <div className="table-scroll" id="intraday-feature-content">
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
      </div>}
    </section>
  );
}

function OpportunityRankingBoard({ rows }: { rows: RankedOpportunity[] }) {
  const [expanded, setExpanded] = useState(true);
  const componentKeys = ["price_trend", "participation", "market_sector", "liquidity_execution", "fundamental", "catalyst"];
  return (
    <section className="table-card opportunity-card">
      <div className="table-heading">
        <div><h2>Explainable opportunity ranking</h2><p>Coverage-adjusted long-continuation candidates, recalculated every completed minute</p></div>
        <div className="table-heading-actions"><span>Pilot v1 · provisional weights · not yet backtested</span><SectionToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} label="Explainable opportunity ranking" /></div>
      </div>
      {expanded && <div className="table-scroll" id="opportunity-ranking-content">
        <table className="opportunity-table">
          <thead><tr><th>Rank</th><th>Stock</th><th>CMP</th><th>Opportunity score</th>{componentKeys.map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}<th>Why it ranks</th><th>Risk / missing</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const components = Object.fromEntries(row.score.components.map((component) => [component.key, component]));
              return (
                <tr key={row.instrument_key}>
                  <td className="rank-cell">{row.rank ?? "—"}</td>
                  <td><strong>{row.symbol}</strong><small>{row.sector ?? "Sector unavailable"}</small><span className={`score-status ${row.score.status}`}>{row.score.status.replaceAll("_", " ")}</span></td>
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
      </div>}
    </section>
  );
}

function EvidenceBoard({ rows }: { rows: OpportunityEvidence[] }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="table-card evidence-card">
      <div className="table-heading">
        <div><h2>Validated evidence confluence</h2><p>Intraday, daily, market-relative, volume and liquidity evidence in one view</p></div>
        <div className="table-heading-actions"><span>Underlying evidence used by the provisional ranking model</span><SectionToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} label="Validated evidence confluence" /></div>
      </div>
      {expanded && <div className="table-scroll" id="validated-evidence-content">
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
      </div>}
    </section>
  );
}

function CorporateActionPanel({ rows, analyses }: { rows: CorporateActionAssessment[]; analyses: CorporateActionAIAnalysis[] }) {
  const [expanded, setExpanded] = useState(true);
  if (!rows.length) return null;
  const aiByEvent = Object.fromEntries(analyses.map((item) => [item.event_id, item]));
  return (
    <section className="table-card corporate-action-card">
      <div className="table-heading">
        <div><h2>Corporate-action materiality</h2><p>Deterministic event metrics based on facts and the pre-event close</p></div>
        <div className="table-heading-actions"><span>Versioned rules · AI is optional and source-grounded</span><SectionToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} label="Corporate-action materiality" /></div>
      </div>
      {expanded && <div className="table-scroll" id="corporate-action-content">
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
        </table>
      </div>}
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
  const [financialResultReport, setFinancialResultReport] = useState<FinancialResultCheckReport | null>(null);
  const [approvedStocksExpanded, setApprovedStocksExpanded] = useState(true);
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

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

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
      const response = await fetch(`${apiBaseUrl}/market/financial-results/check?limit=${runtime?.pilot_size ?? 20}`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json() as { detail?: string };
        throw new Error(payload.detail ?? "Financial results could not be checked");
      }
      setFinancialResultReport(await response.json() as FinancialResultCheckReport);
      await refresh();
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
  const pilotSize = runtime?.pilot_size ?? 20;

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

      <OpportunityRankingBoard rows={opportunities} />

      <FeatureMatrix features={features} />

      <CorporateActionPanel rows={corporateActions} analyses={corporateActionAI} />

      <EvidenceBoard rows={evidence} />

      <DailyRegimePanel regimes={regimes} />

      <section className="table-card">
        <div className="table-heading">
          <div><h2>Approved stocks</h2><p>Latest available one-minute values</p></div>
          <div className="table-heading-actions"><span>Refreshes every 5 seconds · calculations every 60 seconds</span><SectionToggle expanded={approvedStocksExpanded} onToggle={() => setApprovedStocksExpanded((value) => !value)} label="Approved stocks" /></div>
        </div>
        {approvedStocksExpanded && <div className="table-scroll" id="approved-stocks-content">
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
            </tbody>
          </table>
        </div>}
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
