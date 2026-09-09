import { useCallback, useEffect, useState } from "react";

type AuthStatus = { configured: boolean; authenticated: boolean; expires_at: string | null };

type RuntimeStatus = {
  cadence_seconds: number;
  pilot_size: number;
  redis_available: boolean;
  bootstrap: { state: string; total: number; processed: number; history_loaded: number; daily_history_loaded: number; benchmark_daily_loaded: number; sectors_loaded: number; errors: number };
  live: { state: string; connected: boolean; subscribed: number; last_message_at: string | null; scheduled_stop_at: string | null; error: string | null };
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

function MarketContextPanel({ context }: { context: MarketContext | null }) {
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
        <span>As of {new Date(context.as_of).toLocaleTimeString("en-IN")}</span>
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
        <span>No composite score or model weighting yet</span>
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

function Dashboard() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [stocks, setStocks] = useState<WatchlistItem[]>([]);
  const [context, setContext] = useState<MarketContext | null>(null);
  const [features, setFeatures] = useState<StockFeatures[]>([]);
  const [regimes, setRegimes] = useState<DailyRegime[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [statusResponse, watchlistResponse, contextResponse, featuresResponse, regimesResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/market/status`),
        fetch(`${apiBaseUrl}/market/watchlist`),
        fetch(`${apiBaseUrl}/market/context`),
        fetch(`${apiBaseUrl}/market/features`),
        fetch(`${apiBaseUrl}/market/daily-regimes`),
      ]);
      if (!statusResponse.ok || !watchlistResponse.ok) throw new Error("Market service is unavailable");
      setRuntime(await statusResponse.json() as RuntimeStatus);
      setStocks(await watchlistResponse.json() as WatchlistItem[]);
      setContext(contextResponse.ok ? await contextResponse.json() as MarketContext : null);
      setFeatures(featuresResponse.ok ? await featuresResponse.json() as StockFeatures[] : []);
      setRegimes(regimesResponse.ok ? await regimesResponse.json() as DailyRegime[] : []);
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

  const runAction = async (action: "bootstrap" | "live/start" | "live/stop") => {
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

  const bootstrapping = runtime?.bootstrap.state === "running";
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
        <article><span>History</span><strong>{runtime?.bootstrap.history_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Daily regimes</span><strong>{runtime?.bootstrap.daily_history_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Sectors</span><strong>{runtime?.bootstrap.sectors_loaded ?? 0}/{pilotSize}</strong></article>
        <article><span>Subscribed</span><strong>{runtime?.live.subscribed ?? 0}</strong></article>
      </section>

      <MarketContextPanel context={context} />

      <DailyRegimePanel regimes={regimes} />

      <FeatureMatrix features={features} />

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
            </tbody>
          </table>
        </div>
      </section>
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
