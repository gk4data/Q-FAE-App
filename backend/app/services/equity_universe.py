"""Resolve Q-FAE's stock universe against the Upstox NSE instrument master."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import threading
import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

UPSTOX_NSE_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
UPSTOX_SUSPENDED_MASTER_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/suspended-instrument.json.gz"
)
NSE_DAILY_REPORTS_URL = "https://www.nseindia.com/api/daily-reports?key=CM"
NSE_SECURITY_REPORT_KEY = "NSE-CM-SECURITY-CSV"
NSE_BHAVDATA_REPORT_KEY = "CM-BHAVDATA-FULL"
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/all-reports",
}
# NSE identifies SME securities with SM (rolling) and ST/SZ (trade-for-trade).
# BE/BZ are also trade-for-trade series. Q-FAE admits only normal EQ shares.
NSE_MAINBOARD_EQUITY_SERIES = frozenset({"EQ"})
NSE_SME_EQUITY_SERIES = frozenset({"SM", "ST", "SZ"})


@dataclass(frozen=True)
class NseMarketReference:
    """NSE security/share-capital and completed-session close reference."""

    security_as_of: date
    price_as_of: date
    issued_capital: dict[tuple[str, str], float]
    security_type_flags: dict[tuple[str, str], str]
    close_prices: dict[str, float]
    traded_values_inr: dict[str, float]
    security_url: str = ""
    bhavdata_url: str = ""
    security_sha256: str = ""
    bhavdata_sha256: str = ""


def parse_nse_equity_master(compressed_payload: bytes) -> list[dict[str, Any]]:
    """Extract NSE cash-equity series relevant to Q-FAE from the BOD master."""
    try:
        master = json.loads(gzip.decompress(compressed_payload))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Upstox instrument master was not a valid gzip JSON document") from exc

    if not isinstance(master, list):
        raise ValueError("Upstox instrument master has an unexpected top-level structure")

    equities = [
        instrument
        for instrument in master
        if isinstance(instrument, dict)
        and instrument.get("segment") == "NSE_EQ"
        and instrument.get("instrument_type") in NSE_MAINBOARD_EQUITY_SERIES
        and instrument.get("instrument_key")
        and instrument.get("trading_symbol")
    ]
    if not equities:
        raise ValueError("Upstox instrument master contained no NSE equities")
    return equities


def parse_suspended_equities(compressed_payload: bytes) -> set[tuple[str, str, str]]:
    """Return exact suspended-instrument identities from Upstox's daily file."""
    try:
        master = json.loads(gzip.decompress(compressed_payload))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Upstox suspended master was not a valid gzip JSON document") from exc
    if not isinstance(master, list):
        raise ValueError("Upstox suspended master has an unexpected top-level structure")
    return {
        (
            str(item.get("instrument_key") or ""),
            str(item.get("trading_symbol") or "").upper(),
            str(item.get("instrument_type") or "").upper(),
        )
        for item in master
        if isinstance(item, dict)
        and item.get("instrument_key")
        and item.get("trading_symbol")
        and item.get("instrument_type")
    }


def _csv_rows(payload: bytes, *, compressed: bool) -> list[dict[str, str]]:
    try:
        raw = gzip.decompress(payload) if compressed else payload
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("NSE report was not a readable CSV document") from exc
    reader = csv.DictReader(io.StringIO(text))
    return [
        {
            str(key or "").strip(): str(value or "").strip()
            for key, value in row.items()
        }
        for row in reader
    ]


def parse_nse_market_reference(
    security_payload: bytes,
    bhavdata_payload: bytes,
    *,
    security_as_of: date,
    price_as_of: date,
) -> NseMarketReference:
    """Parse official NSE reports used to identify companies and compute market cap."""
    issued_capital: dict[tuple[str, str], float] = {}
    security_type_flags: dict[tuple[str, str], str] = {}
    for row in _csv_rows(security_payload, compressed=True):
        if row.get("SctySrs", "").upper() != "EQ":
            continue
        isin = row.get("ISIN", "").upper()
        symbol = row.get("TckrSymb", "").upper()
        if not isin or not symbol:
            continue
        identity = (isin, symbol)
        security_type_flags[identity] = row.get("SctyTpFlg", "")
        try:
            capital = float(row.get("IssdCptl") or 0)
        except ValueError:
            capital = 0
        if capital > 0:
            issued_capital[identity] = capital

    close_prices: dict[str, float] = {}
    traded_values_inr: dict[str, float] = {}
    for row in _csv_rows(bhavdata_payload, compressed=False):
        if row.get("SERIES", "").upper() != "EQ":
            continue
        symbol = row.get("SYMBOL", "").upper()
        if not symbol:
            continue
        try:
            close_price = float(row.get("CLOSE_PRICE") or row.get("PREV_CLOSE") or 0)
            turnover_lacs = float(row.get("TURNOVER_LACS") or 0)
        except ValueError:
            continue
        if close_price > 0:
            close_prices[symbol] = close_price
        if turnover_lacs >= 0:
            traded_values_inr[symbol] = turnover_lacs * 100_000.0

    if not security_type_flags:
        raise ValueError("NSE security report contained no EQ securities")
    if not close_prices:
        raise ValueError("NSE bhavdata report contained no EQ closing prices")
    return NseMarketReference(
        security_as_of=security_as_of,
        price_as_of=price_as_of,
        issued_capital=issued_capital,
        security_type_flags=security_type_flags,
        close_prices=close_prices,
        traded_values_inr=traded_values_inr,
    )


def _candidate(instrument: dict[str, Any]) -> dict[str, Any]:
    return {
        "trading_symbol": instrument["trading_symbol"],
        "instrument_key": instrument["instrument_key"],
        "isin": instrument.get("isin"),
        "name": instrument.get("name"),
        "short_name": instrument.get("short_name"),
        "exchange": instrument.get("exchange"),
        "segment": instrument.get("segment"),
        "instrument_type": instrument.get("instrument_type"),
        "tick_size": instrument.get("tick_size"),
        "lot_size": instrument.get("lot_size"),
    }


def build_dynamic_universe(
    master: list[dict[str, Any]],
    suspended: set[tuple[str, str, str]],
    market_reference: NseMarketReference,
    *,
    minimum_market_cap_crore: float,
    minimum_share_price_inr: float = 20.0,
) -> list[dict[str, Any]]:
    """Build the provider-led eligible NSE company universe."""

    rows: list[dict[str, Any]] = []
    for instrument in master:
        key = str(instrument["instrument_key"])
        symbol = str(instrument["trading_symbol"]).upper()
        instrument_type = str(instrument.get("instrument_type") or "").upper()
        isin = str(instrument.get("isin") or "").upper()
        identity = (isin, symbol)
        suspended_identity = (key, symbol, instrument_type)
        security_flag = market_reference.security_type_flags.get(identity)
        issued_capital = market_reference.issued_capital.get(identity)
        close_price = market_reference.close_prices.get(symbol)
        market_cap_crore = (
            issued_capital * close_price / 10_000_000.0
            if issued_capital is not None and close_price is not None
            else None
        )

        if suspended_identity in suspended:
            status = "excluded_suspended"
            reason = "Upstox daily suspended-instrument list"
        elif security_flag is not None and security_flag != "0":
            status = "excluded_non_company"
            reason = f"NSE security type flag {security_flag} is not an equity company"
        elif security_flag is None or market_cap_crore is None:
            status = "excluded_missing_market_cap"
            reason = "Official NSE issued capital or completed-session close is unavailable"
        elif close_price < minimum_share_price_inr:
            status = "excluded_share_price"
            reason = f"Latest completed close is below Rs {minimum_share_price_inr:,.2f}"
        elif market_cap_crore < minimum_market_cap_crore:
            status = "excluded_market_cap"
            reason = f"Market cap is below Rs {minimum_market_cap_crore:,.0f} crore"
        else:
            status = "resolved"
            reason = None

        rows.append(
            {
                "requested_name": instrument.get("name") or instrument.get("short_name") or symbol,
                "status": status,
                "exclusion_reason": reason,
                "market_cap_crore": round(market_cap_crore, 2) if market_cap_crore is not None else None,
                "market_cap_as_of": market_reference.price_as_of.isoformat(),
                "latest_close_price": close_price,
                "daily_traded_value_inr": market_reference.traded_values_inr.get(symbol),
                "nse_security_type_flag": security_flag,
                "candidate": _candidate(instrument),
            }
        )

    status_order = {
        "resolved": 0,
        "excluded_share_price": 1,
        "excluded_market_cap": 2,
        "excluded_missing_market_cap": 3,
        "excluded_non_company": 4,
        "excluded_suspended": 5,
    }
    rows.sort(
        key=lambda row: (
            status_order.get(str(row["status"]), 9),
            -float(row.get("daily_traded_value_inr") or 0),
            -float(row.get("market_cap_crore") or 0),
            str(row["candidate"]["trading_symbol"]),
        )
    )
    return rows


class EquityUniverseService:
    """Refresh and load the repository's Upstox-aligned equity universe."""

    def __init__(
        self,
        output_path: Path,
        *,
        minimum_market_cap_crore: float = 500.0,
        minimum_share_price_inr: float = 20.0,
    ) -> None:
        self.output_path = output_path
        self.minimum_market_cap_crore = minimum_market_cap_crore
        self.minimum_share_price_inr = minimum_share_price_inr
        self._refresh_lock = threading.Lock()

    def refresh(self) -> dict[str, Any]:
        """Download the current master and atomically write the resolved universe."""
        with self._refresh_lock:
            compressed_master = self._download_master()
            master = parse_nse_equity_master(compressed_master)
            suspended_payload = self._download_suspended_master()
            suspended = parse_suspended_equities(suspended_payload)
            market_reference = self._download_market_reference()
            instruments = build_dynamic_universe(
                master,
                suspended,
                market_reference,
                minimum_market_cap_crore=self.minimum_market_cap_crore,
                minimum_share_price_inr=self.minimum_share_price_inr,
            )
            summary = {
                "provider_eq_total": len(instruments),
                "resolved": sum(row["status"] == "resolved" for row in instruments),
                "excluded_market_cap": sum(row["status"] == "excluded_market_cap" for row in instruments),
                "excluded_share_price": sum(row["status"] == "excluded_share_price" for row in instruments),
                "excluded_missing_market_cap": sum(
                    row["status"] == "excluded_missing_market_cap" for row in instruments
                ),
                "excluded_non_company": sum(row["status"] == "excluded_non_company" for row in instruments),
                "excluded_suspended": sum(row["status"] == "excluded_suspended" for row in instruments),
                "minimum_market_cap_crore": self.minimum_market_cap_crore,
                "minimum_share_price_inr": self.minimum_share_price_inr,
            }
            payload = {
                "schema_version": 3,
                "generated_at": datetime.now(UTC).isoformat(),
                "source": {
                    "upstox_master_url": UPSTOX_NSE_MASTER_URL,
                    "upstox_master_sha256": hashlib.sha256(compressed_master).hexdigest(),
                    "upstox_suspended_master_url": UPSTOX_SUSPENDED_MASTER_URL,
                    "upstox_suspended_master_sha256": hashlib.sha256(suspended_payload).hexdigest(),
                    "nse_security_url": market_reference.security_url,
                    "nse_security_sha256": market_reference.security_sha256,
                    "nse_security_as_of": market_reference.security_as_of.isoformat(),
                    "nse_bhavdata_url": market_reference.bhavdata_url,
                    "nse_bhavdata_sha256": market_reference.bhavdata_sha256,
                    "nse_bhavdata_as_of": market_reference.price_as_of.isoformat(),
                },
                "summary": summary,
                "instruments": instruments,
            }
            self._write_atomically(payload)
            return payload

    def load(self) -> dict[str, Any]:
        """Load the latest generated universe without reaching Upstox."""
        if not self.output_path.is_file():
            raise FileNotFoundError("Instrument universe has not been generated yet")
        return json.loads(self.output_path.read_text(encoding="utf-8"))

    def _download_master(self) -> bytes:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(UPSTOX_NSE_MASTER_URL)
            response.raise_for_status()
            return response.content

    def _download_suspended_master(self) -> bytes:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(UPSTOX_SUSPENDED_MASTER_URL)
            response.raise_for_status()
            return response.content

    def _download_market_reference(self) -> NseMarketReference:
        with httpx.Client(timeout=60.0, follow_redirects=True, headers=_NSE_HEADERS) as client:
            response = client.get(NSE_DAILY_REPORTS_URL)
            response.raise_for_status()
            manifest = response.json()
            security_report = self._latest_report(manifest, NSE_SECURITY_REPORT_KEY)
            bhavdata_report = self._latest_report(manifest, NSE_BHAVDATA_REPORT_KEY)
            security_url = self._report_url(security_report)
            bhavdata_url = self._report_url(bhavdata_report)
            security_response = client.get(security_url)
            security_response.raise_for_status()
            bhavdata_response = client.get(bhavdata_url)
            bhavdata_response.raise_for_status()

        reference = parse_nse_market_reference(
            security_response.content,
            bhavdata_response.content,
            security_as_of=self._report_date(security_report),
            price_as_of=self._report_date(bhavdata_report),
        )
        return NseMarketReference(
            **{
                **reference.__dict__,
                "security_url": security_url,
                "bhavdata_url": bhavdata_url,
                "security_sha256": hashlib.sha256(security_response.content).hexdigest(),
                "bhavdata_sha256": hashlib.sha256(bhavdata_response.content).hexdigest(),
            }
        )

    @classmethod
    def _latest_report(cls, manifest: Any, file_key: str) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            raise ValueError("NSE daily-report manifest has an unexpected structure")
        matches = [
            row
            for bucket in ("CurrentDay", "PreviousDay")
            for row in manifest.get(bucket, [])
            if isinstance(row, dict) and row.get("fileKey") == file_key
        ]
        if not matches:
            raise ValueError(f"NSE daily-report manifest did not include {file_key}")
        return max(matches, key=cls._report_date)

    @staticmethod
    def _report_date(report: dict[str, Any]) -> date:
        try:
            return datetime.strptime(str(report["tradingDate"]), "%d-%b-%Y").date()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("NSE daily report has an invalid trading date") from exc

    @staticmethod
    def _report_url(report: dict[str, Any]) -> str:
        path = str(report.get("filePath") or "")
        filename = str(report.get("fileActlName") or "")
        if not path.startswith("https://") or not filename:
            raise ValueError("NSE daily report has an invalid file location")
        return f"{path.rstrip('/')}/{filename}"

    def _write_atomically(self, payload: dict[str, Any]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.output_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary_path.replace(self.output_path)
