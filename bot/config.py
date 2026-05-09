"""Конфигурация бота — читает переменные окружения через pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    # NoDecode: оставляем исходную строку, распарсим сами в валидаторе ниже.
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list, alias="ADMIN_IDS")
    db_path: Path = Field(Path("./data/bot.sqlite3"), alias="DB_PATH")

    prepay_min_rub: int = Field(100_000, alias="PREPAY_MIN_RUB")
    prepay_pct: int = Field(15, alias="PREPAY_PCT")

    # Реквизиты получателя для PDF-счетов и QR-кода (ГОСТ Р 56042-2014).
    # По умолчанию подставлены боевые реквизиты самозанятого; при необходимости
    # переопределяются через переменные окружения.
    payee_name: str = Field("АКОПЯН АРТУР КАРОЕВИЧ", alias="PAYEE_NAME")
    payee_inn: str = Field("772402520705", alias="PAYEE_INN")
    payee_tax_regime: str = Field("НПД (самозанятый)", alias="PAYEE_TAX_REGIME")
    payee_account: str = Field("40817810800106508636", alias="PAYEE_ACCOUNT")
    payee_bank_name: str = Field("АО «ТИНЬКОФФ БАНК»", alias="PAYEE_BANK_NAME")
    payee_bik: str = Field("044525974", alias="PAYEE_BIK")
    payee_corr_account: str = Field("30101810145250000974", alias="PAYEE_CORR_ACCOUNT")
    payee_email: str = Field("karoak@mail.ru", alias="PAYEE_EMAIL")
    # Телефон для приёма СБП-перевода. Если пусто — клиенту показывается
    # только инструкция по реквизитам (ГОСТ Р QR). Если указано — добавляется
    # отдельный блок «Перевод СБП по номеру: +7…» в caption к QR.
    payee_phone: str | None = Field(None, alias="PAYEE_PHONE")

    tz: str = Field("Europe/Moscow", alias="TZ")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: object) -> list[int]:
        if v is None or v == "":
            return []
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        # строка: "1,2,3" или "1 2 3"
        raw = str(v).replace(" ", ",").replace(";", ",")
        return [int(x) for x in raw.split(",") if x.strip()]

    @property
    def db_url(self) -> str:
        # SQLAlchemy async url
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
