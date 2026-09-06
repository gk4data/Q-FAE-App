import { useEffect, useState } from "react";

type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
  expires_at: string | null;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const result = new URLSearchParams(window.location.search).get("auth");

  useEffect(() => {
    void fetch(`${apiBaseUrl}/auth/upstox/status`)
      .then((response) => response.json() as Promise<AuthStatus>)
      .then(setAuth)
      .catch(() => setAuth({ configured: false, authenticated: false, expires_at: null }));
  }, []);

  const startLogin = () => {
    window.location.assign(`${apiBaseUrl}/auth/upstox/login`);
  };

  return (
    <main className="auth-shell">
      <section className="brand-panel">
        <p className="brand-name" aria-label="Q FAE">
          <span>Q</span><i>&middot;</i><span>FAE</span><i className="brand-arrow" aria-hidden="true">↑</i>
        </p>
        <p className="brand-full-form">Quantitative Financial Algorithms for Equity</p>
        <h1>See the market<br />with more clarity.</h1>
        <p>Real-time Indian equity intelligence, built around evidence rather than noise.</p>
      </section>
      <section className="login-panel" aria-label="Upstox sign in">
        <p className="eyebrow">CONNECT DATA</p>
        <h2>Sign in to begin</h2>
        <p className="description">Connect your Upstox account to enable read-only market data access.</p>
        {result === "success" && <p className="notice success">Upstox is connected.</p>}
        {result === "failed" && <p className="notice error">Sign-in could not be completed. Please try again.</p>}
        {result === "cancelled" && <p className="notice error">Sign-in was cancelled.</p>}
        {auth?.authenticated ? (
          <p className="notice success">Authenticated until {new Date(auth.expires_at!).toLocaleString()}.</p>
        ) : (
          <button type="button" onClick={startLogin} disabled={!auth?.configured}>
            Continue with Upstox
          </button>
        )}
        {!auth && <p className="status">Checking secure connection...</p>}
        {auth && !auth.configured && <p className="status">Upstox OAuth needs local configuration.</p>}
        <p className="fine-print">Your access token stays in the Q-FAE backend and is never sent to this page.</p>
      </section>
    </main>
  );
}
