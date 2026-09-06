import gzip
import json
from pathlib import Path

from openpyxl import Workbook

from app.services.equity_universe import EquityUniverseService, load_stock_list, parse_nse_equity_master, resolve_stock_list


def _write_stock_list(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Sr No", "Name"])
    sheet.append([1, "Acme Industries"])
    sheet.append([2, "Unlisted Example"])
    workbook.save(path)


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
    ]
    return gzip.compress(json.dumps(master).encode("utf-8"))


def test_resolver_keeps_unmatched_names_for_review(tmp_path: Path) -> None:
    stock_list_path = tmp_path / "Stock List.xlsx"
    _write_stock_list(stock_list_path)

    entries = load_stock_list(stock_list_path)
    master = parse_nse_equity_master(_compressed_master())
    results = resolve_stock_list(entries, master)

    assert results[0]["status"] == "resolved"
    assert results[0]["candidate"]["instrument_key"] == "NSE_EQ|INE000A01010"
    assert results[1]["status"] == "unmatched"


def test_refresh_writes_a_versioned_universe_file(tmp_path: Path, monkeypatch) -> None:
    stock_list_path = tmp_path / "Stock List.xlsx"
    output_path = tmp_path / "data" / "instruments" / "universe.json"
    _write_stock_list(stock_list_path)
    service = EquityUniverseService(stock_list_path, output_path)
    monkeypatch.setattr(service, "_download_master", _compressed_master)

    payload = service.refresh()

    assert output_path.is_file()
    assert payload["summary"] == {"requested": 2, "resolved": 1, "needs_review": 0, "unmatched": 1}
    assert service.load()["source"]["stock_list"] == "Stock List.xlsx"
