from sqlalchemy import URL

from app.core.config import Settings
from app.db.engine import get_database_url


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
