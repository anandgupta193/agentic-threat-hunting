import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_window_hours_must_divide_24() -> None:
    assert make(window_hours=6).window_hours == 6
    with pytest.raises(ValidationError, match="WINDOW_HOURS must divide 24"):
        make(window_hours=5)


def test_db_url_built_from_parts_unless_overridden() -> None:
    assert make(postgres_host="h", postgres_port=1234).db_url.endswith("@h:1234/threat_hunt")
    assert make(database_url="postgresql+asyncpg://x@y/z").db_url == "postgresql+asyncpg://x@y/z"
