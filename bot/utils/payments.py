"""Mock-реализация платёжных потоков (СБП QR + счёт PDF).

В боевой версии тут были бы интеграции с банком/платёжкой. Сейчас это заглушки,
которые генерируют картинку QR (любую строку) и PDF-счёт.
"""

from __future__ import annotations

import io
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..config import get_settings


def prepay_line(prepay_rub: int, kind: str | None = None) -> str:
    """Строка вида «Предоплата 15% (не менее 100 000 ₽): 375 000 ₽».

    Оговорка про минимум отображается только для ``kind == "car"``,
    потому что для запчастей и покупок минимум не применяется.
    """
    st = get_settings()
    suffix = f" (не менее {st.prepay_min_rub:,} ₽)".replace(",", " ") if kind == "car" else ""
    return f"Предоплата {st.prepay_pct}%{suffix}: {prepay_rub:,} ₽".replace(",", " ")


# ---------- попытаемся подхватить кириллический шрифт ---------- #
_REGISTERED_FONT = "Helvetica"
for _candidate in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
):
    try:
        pdfmetrics.registerFont(TTFont("Body", _candidate))
        _REGISTERED_FONT = "Body"
        break
    except Exception:
        continue


def compute_prepayment(total_rub: int, kind: str | None = None) -> int:
    """Расчёт предоплаты.

    Правила (по ТЗ):
      * автомобиль (kind == "car") — 15% от суммы, но не меньше ``prepay_min_rub``;
      * запчасти и покупки (любой другой kind) — ровно 15% от суммы,
        минимум не применяется.
    """
    st = get_settings()
    calc = total_rub * st.prepay_pct // 100
    if kind == "car":
        return max(calc, st.prepay_min_rub)
    return calc


def make_sbp_qr(
    offer_id: int,
    user_tg_id: int,
    amount_rub: int,
) -> tuple[bytes, str]:
    """Сгенерировать PNG с QR-кодом (mock). Возвращает (png_bytes, payload_str)."""
    payload = (
        "https://qr.nspk.ru/AD10000000000000000000000000000000"
        f"?type=02&bank=100000000010&sum={amount_rub * 100}"
        f"&cur=RUB&crc={offer_id:08x}"
    )
    img = qrcode.make(payload, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), payload


def make_invoice_pdf(
    offer_id: int,
    user_tg_id: int,
    user_name: str | None,
    title: str,
    description: str,
    total_rub: int,
    prepay_rub: int,
    kind: str | None = None,
) -> bytes:
    """Сгенерировать PDF-счёт на предоплату (mock). Возвращает байты PDF."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFont(_REGISTERED_FONT, 16)
    c.drawString(2 * cm, h - 2 * cm, "Счёт на предоплату")

    c.setFont(_REGISTERED_FONT, 11)
    y = h - 3.2 * cm
    line_h = 0.6 * cm

    lines = [
        f"Счёт № ETP-{offer_id:06d} от {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"Заказчик: {user_name or '—'} (Telegram ID {user_tg_id})",
        "",
        f"Наименование: {title}",
        f"Описание: {description[:200]}",
        "",
        f"Полная сумма: {total_rub:,} ₽".replace(",", " "),
        prepay_line(prepay_rub, kind=kind),
        "",
        "Реквизиты для оплаты (mock):",
        "  Получатель: ООО «ERA ETP»",
        "  ИНН: 7728282160",
        "  Расч. счёт: 40702810000000000001",
        "  Банк: ПАО «МОСКОВСКИЙ КРЕДИТНЫЙ БАНК»",
        "  БИК: 044525659",
        "  Корр. счёт: 30101810745250000659",
        "",
        "Назначение платежа: предоплата по офферу ETP-"
        f"{offer_id:06d} (без НДС).",
    ]
    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= line_h

    c.setFont(_REGISTERED_FONT, 9)
    c.drawString(
        2 * cm,
        2 * cm,
        "Документ сгенерирован автоматически era_etp_bot. Не требует подписи (mock).",
    )
    c.showPage()
    c.save()
    return buf.getvalue()
