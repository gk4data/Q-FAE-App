import gzip
import json
from datetime import date
from pathlib import Path

from app.services.equity_universe import (
    EquityUniverseService,
    NseMarketReference,
    build_dynamic_universe,
    parse_nse_equity_master,
    parse_nse_market_reference,
)


def _compressed_master() -> bytes:
    master = [
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "name": "ACME INDUSTRIES LIMITED",
            "short_name": "Acme Industries",
            "trading_symbol": "ACME",
            "instrument_key": "NSE_EQ|INE000A01010",
            "isin": "INE000A01010",
            "exchange": "NSE",
            "tick_size": 5.0,
            "lot_size": 1,
        },
        {
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "trading_symbol": "ACMEFUT",
            "instrument_key": "NSE_FO|1",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "SG",
            "trading_symbol": "GSEC",
            "instrument_key": "NSE_EQ|INE000A01011",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "SM",
            "name": "SMALL BUSINESS LIMITED",
            "short_name": "Small Business",
            "trading_symbol": "SMALLBIZ",
            "instrument_key": "NSE_EQ|INE000A01012",
            "isin": "INE000A01012",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "ST",
            "name": "SME TRADE FOR TRADE LIMITED",
            "short_name": "SME Trade For Trade",
            "trading_symbol": "SMETFT",
            "instrument_key": "NSE_EQ|INE000A01013",
            "isin": "INE000A01013",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "BE",
            "name": "MAIN BOARD TRADE FOR TRADE LIMITED",
            "short_name": "Main Board Trade For Trade",
            "trading_symbol": "MAINBE",
            "instrument_key": "NSE_EQ|INE000A01014",
            "isin": "INE000A01014",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "BZ",
            "name": "NON COMPLIANT TRADE FOR TRADE LIMITED",
            "short_name": "Non Compliant Trade For Trade",
            "trading_symbol": "MAINBZ",
            "instrument_key": "NSE_EQ|INE000A01015",
            "isin": "INE000A01015",
        },
    ]
    return gzip.compress(json.dumps(master).encode("utf-8"))


def test_instrument_master_accepts_only_normal_eq_series() -> None:
    master = parse_nse_equity_master(_compressed_master())

    assert {item["instrument_type"] for item in master} == {"EQ"}
    assert {item["trading_symbol"] for item in master} == {"ACME"}


def test_refresh_writes_a_versioned_universe_file(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "data" / "instruments" / "universe.json"
    service = EquityUniverseService(output_path)
    monkeypatch.setattr(service, "_download_master", _compressed_master)
    monkeypatch.setattr(service, "_download_suspended_master", lambda: gzip.compress(b"[]"))
    reference = NseMarketReference(
        security_as_of=date(2026, 10, 9),
        price_as_of=date(2026, 10, 9),
        issued_capital={("INE000A01010", "ACME"): 10_000_000},
        security_type_flags={("INE000A01010", "ACME"): "0"},
        close_prices={"ACME": 600.0},
        traded_values_inr={"ACME": 100_000_000.0},
        security_url="https://example.test/security.csv.gz",
        bhavdata_url="https://example.test/bhavdata.csv",
    )
    monkeypatch.setattr(service, "_download_market_reference", lambda: reference)

    payload = service.refresh()

    assert output_path.is_file()
    assert payload["schema_version"] == 3
    assert payload["summary"]["provider_eq_total"] == 1
    assert payload["summary"]["resolved"] == 1
    assert payload["summary"]["minimum_market_cap_crore"] == 500.0
    assert service.load()["source"]["upstox_master_url"].startswith("https://")


def test_market_reference_parses_company_type_capital_close_and_turnover() -> None:
    security_csv = (
        "FinInstrmId,TckrSymb,SctySrs,ISIN,SctyTpFlg,IssdCptl\n"
        "1,ACME,EQ,INE000A01010,0,10000000\n"
        "2,ACMEETF,EQ,INF000A01010,4,5000000\n"
    ).encode()
    bhavdata_csv = (
        "SYMBOL, SERIES, PREV_CLOSE, CLOSE_PRICE, TURNOVER_LACS\n"
        " ACME , EQ ,590,600,125.5\n"
        " ACMEETF , EQ ,100,101,2\n"
    ).encode()

    reference = parse_nse_market_reference(
        gzip.compress(security_csv),
        bhavdata_csv,
        security_as_of=date(2026, 10, 9),
        price_as_of=date(2026, 10, 9),
    )

    assert reference.security_type_flags[("INE000A01010", "ACME")] == "0"
    assert reference.security_type_flags[("INF000A01010", "ACMEETF")] == "4"
    assert reference.close_prices["ACME"] == 600.0
    assert reference.traded_values_inr["ACME"] == 12_550_000.0


def test_dynamic_universe_applies_market_cap_and_non_company_gates() -> None:
    master = parse_nse_equity_master(_compressed_master())
    master.extend(
        [
            {
                "segment": "NSE_EQ",
                "instrument_type": "EQ",
                "name": "LOW CAP LIMITED",
                "trading_symbol": "LOWCAP",
                "instrument_key": "NSE_EQ|INE000A01020",
                "isin": "INE000A01020",
            },
            {
                "segment": "NSE_EQ",
                "instrument_type": "EQ",
                "name": "INDEX ETF",
                "trading_symbol": "INDEXETF",
                "instrument_key": "NSE_EQ|INF000A01020",
                "isin": "INF000A01020",
            },
            {
                "segment": "NSE_EQ",
                "instrument_type": "EQ",
                "name": "PENNY LIMITED",
                "trading_symbol": "PENNY",
                "instrument_key": "NSE_EQ|INE000A01030",
                "isin": "INE000A01030",
            },
        ]
    )
    reference = NseMarketReference(
        security_as_of=date(2026, 10, 9),
        price_as_of=date(2026, 10, 9),
        issued_capital={
            ("INE000A01010", "ACME"): 10_000_000,
            ("INE000A01020", "LOWCAP"): 10_000_000,
            ("INF000A01020", "INDEXETF"): 10_000_000,
            ("INE000A01030", "PENNY"): 1_000_000_000,
        },
        security_type_flags={
            ("INE000A01010", "ACME"): "0",
            ("INE000A01020", "LOWCAP"): "0",
            ("INF000A01020", "INDEXETF"): "4",
            ("INE000A01030", "PENNY"): "0",
        },
        close_prices={"ACME": 500.0, "LOWCAP": 499.99, "INDEXETF": 100.0, "PENNY": 19.99},
        traded_values_inr={},
    )

    rows = build_dynamic_universe(
        master,
        set(),
        reference,
        minimum_market_cap_crore=500.0,
    )
    by_symbol = {row["candidate"]["trading_symbol"]: row for row in rows}

    assert by_symbol["ACME"]["status"] == "resolved"
    assert by_symbol["ACME"]["market_cap_crore"] == 500.0
    assert by_symbol["LOWCAP"]["status"] == "excluded_market_cap"
    assert by_symbol["INDEXETF"]["status"] == "excluded_non_company"
    assert by_symbol["PENNY"]["status"] == "excluded_share_price"


def test_resolved_universe_order_does_not_rank_by_previous_day_turnover() -> None:
    master = [
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "name": "ZETA LIMITED",
            "trading_symbol": "ZETA",
            "instrument_key": "NSE_EQ|INE000A01040",
            "isin": "INE000A01040",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "name": "ALPHA LIMITED",
            "trading_symbol": "ALPHA",
            "instrument_key": "NSE_EQ|INE000A01041",
            "isin": "INE000A01041",
        },
    ]
    reference = NseMarketReference(
        security_as_of=date(2026, 10, 15),
        price_as_of=date(2026, 10, 15),
        issued_capital={
            ("INE000A01040", "ZETA"): 10_000_000,
            ("INE000A01041", "ALPHA"): 10_000_000,
        },
        security_type_flags={
            ("INE000A01040", "ZETA"): "0",
            ("INE000A01041", "ALPHA"): "0",
        },
        close_prices={"ZETA": 600.0, "ALPHA": 600.0},
        traded_values_inr={"ZETA": 1_000_000_000.0, "ALPHA": 10_000_000.0},
    )

    rows = build_dynamic_universe(
        master,
        set(),
        reference,
        minimum_market_cap_crore=500.0,
    )

    assert [row["candidate"]["trading_symbol"] for row in rows] == ["ALPHA", "ZETA"]
