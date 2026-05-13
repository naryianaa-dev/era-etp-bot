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
    # По умолчанию подставлены боевые реквизиты ООО «Форсаж»; при необходимости
    # переопределяются через переменные окружения (Railway / .env).
    payee_name: str = Field("ООО «Форсаж»", alias="PAYEE_NAME")
    payee_inn: str = Field("7728282160", alias="PAYEE_INN")
    payee_kpp: str | None = Field("773001001", alias="PAYEE_KPP")
    payee_tax_regime: str = Field("ОСНО (юридическое лицо)", alias="PAYEE_TAX_REGIME")
    payee_account: str = Field("40702810101500033019", alias="PAYEE_ACCOUNT")
    payee_bank_name: str = Field("ООО «Банк Точка»", alias="PAYEE_BANK_NAME")
    payee_bik: str = Field("044525104", alias="PAYEE_BIK")
    payee_corr_account: str = Field("30101810745374525104", alias="PAYEE_CORR_ACCOUNT")
    # Юридический / почтовый адрес получателя — попадает в PDF-счёт.
    payee_address: str | None = Field(
        "121059, г. Москва, ул. Киевская, д. 14, оф. 2а",
        alias="PAYEE_ADDRESS",
    )
    payee_email: str | None = Field(None, alias="PAYEE_EMAIL")
    # Телефон для приёма СБП-перевода. Если пусто — клиенту показывается
    # только инструкция по реквизитам (ГОСТ Р QR). Если указано — добавляется
    # отдельный блок «Перевод СБП по номеру: +7…» в caption к QR.
    payee_phone: str | None = Field(None, alias="PAYEE_PHONE")
    # Прямая ссылка на быструю оплату (например, статичная Tinkoff
    # «tinkoff.ru/rm/...»). Если задана — клиент получает inline-кнопку
    # «💳 Оплатить N ₽», которая открывает банк/браузер, и не страдает с
    # ручным вводом. ГОСТ Р QR остаётся как fallback.
    payee_payment_url: str | None = Field(None, alias="PAYEE_PAYMENT_URL")

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
