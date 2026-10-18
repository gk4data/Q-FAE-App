from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import URL, create_engine, insert

from app.core.config import Settings
from app.db.engine import get_database_url
from app.db.models import MarketCandleRecord
from app.db.repository import HistoricalMarketRepository


def test_database_url_safely_encodes_discrete_settings() -> None:
    settings = Settings(
        _env_file=None,
        qfae_database_url=None,
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="qfae",
        postgres_user="qfae",
        postgres_password="special@password:with/slash",
    )

    url = get_database_url(settings)

    assert isinstance(url, URL)
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "special@password:with/slash"
    assert "special@password" not in str(url)


def test_plain_postgresql_url_uses_psycopg_driver() -> None:
    settings = Settings(
        _env_file=None,
        qfae_database_url="postgresql://qfae:password@database.example/qfae",
    )

    assert get_database_url(settings).startswith("postgresql+psycopg://")


def test_bounded_candle_query_applies_limit_per_instrument() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    MarketCandleRecord.__table__.create(engine)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    rows = []
    for instrument_key in ("NSE_EQ|A", "NSE_EQ|B"):
        for day in range(4):
            rows.append(
                {
                    "instrument_key": instrument_key,
                    "interval": "day",
                    "timestamp": start + timedelta(days=day),
                    "open": Decimal("100"),
                    "high": Decimal("102"),
                    "low": Decimal("99"),
                    "close": Decimal(str(100 + day)),
                    "volume": 1_000 + day,
                    "open_interest": 0,
                    "source": "upstox",
                    "adjustment_status": "raw",
                }
            )
    with engine.begin() as connection:
        connection.execute(insert(MarketCandleRecord), rows)

    result = HistoricalMarketRepository(engine).get_candles_many(
        ["NSE_EQ|A", "NSE_EQ|B"],
        "day",
        limit=2,
    )

    assert {key: [item.close for item in candles] for key, candles in result.items()} == {
        "NSE_EQ|A": [102.0, 103.0],
        "NSE_EQ|B": [102.0, 103.0],
    }
