"""Платёжные потоки: банковский QR (ГОСТ Р 56042-2014) и PDF-счёт.

QR-код формируется в формате ГОСТ Р 56042-2014 — это универсальный
российский стандарт «банковский QR-код для платёжных документов».
Сканер любого крупного банка РФ (Тинькофф, Сбер, Альфа, ВТБ и т.д.)
парсит этот формат и автоматически заполняет форму перевода:
получатель, ИНН, БИК, расч. счёт, корр. счёт, сумма и назначение.

PDF-счёт содержит те же реквизиты в человекочитаемом виде.

Реквизиты получателя берутся из настроек (см. ``bot/config.py``,
поля ``payee_*``); по умолчанию — боевые реквизиты самозанятого
(НПД), при необходимости переопределяются через переменные окружения.
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


def _format_phone_human(raw: str) -> str:
    """``+79991234567`` → ``+7 (999) 123-45-67``. Любые сторонние пробелы/скобки игнорируются."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        d = digits
        return f"+7 ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}"
    return raw


def payment_caption(offer_id: int, prepay_rub: int) -> str:
    """Caption к QR/PDF с инструкцией по оплате.

    Возвращает HTML-готовый текст. Если в настройках задан ``payee_phone`` —
    добавляется блок про быстрый СБП-перевод по номеру (НСПК публичного API
    для C2C QR не отдаёт, поэтому номер вводится в банке вручную). Универсальный
    ГОСТ Р 56042-2014 QR работает в любом случае — отдаётся как картинка.
    """
    st = get_settings()
    amount_str = f"{prepay_rub:,} ₽".replace(",", " ")
    purpose = f"Предоплата по офферу ETP-{offer_id:06d}"

    parts: list[str] = [
        f"📱 <b>Оплата — оффер #{offer_id}</b>",
        "",
        f"<b>Сумма:</b> {amount_str}",
        f"<b>Назначение:</b> {purpose}",
        f"<b>Получатель:</b> {st.payee_name} (НПД, ИНН {st.payee_inn})",
        "",
    ]
    if st.payee_phone:
        phone_human = _format_phone_human(st.payee_phone)
        parts.extend(
            [
                "<b>Способ 1 — СБП по номеру телефона:</b>",
                f"📞 <code>{phone_human}</code> ({st.payee_bank_name})",
                "В приложении банка → СБП → Перевод по номеру → "
                "ввести номер вручную, выбрать банк получателя, ввести сумму.",
                "",
            ]
        )
    parts.extend(
        [
            "<b>Способ 2 — отсканировать QR-код ниже:</b>",
            "Любое банковское приложение РФ (Тинькофф/Сбер/Альфа/ВТБ) "
            "распознает QR (ГОСТ Р 56042-2014) и автоматически заполнит "
            "форму перевода — реквизиты + сумма + назначение.",
            "",
            "После оплаты нажмите «✅ Я оплатил» ниже — мы свяжемся с вами "
            "и пришлём чек самозанятого.",
        ]
    )
    return "\n".join(parts)


def _gost_qr_payload(amount_rub: int, purpose: str) -> str:
    """Формирует payload в формате ГОСТ Р 56042-2014.

    Стандарт «Банковский QR-код для платёжных документов».
    ``Sum`` указывается в копейках. Поле-разделитель — ``|``
    (общепринятый в банковских приложениях; CRLF тоже допускается
    стандартом, но ``|`` парсится во всех протестированных банках).

    Минимальный набор полей: Name, PersonalAcc, BankName, BIC, CorrespAcc.
    Опциональные: Sum, Purpose, PayeeINN.
    """
    st = get_settings()
    fields = [
        "ST00012",
        f"Name={st.payee_name}",
        f"PersonalAcc={st.payee_account}",
        f"BankName={st.payee_bank_name}",
        f"BIC={st.payee_bik}",
        f"CorrespAcc={st.payee_corr_account}",
        f"Sum={amount_rub * 100}",
        f"Purpose={purpose}",
        f"PayeeINN={st.payee_inn}",
    ]
    return "|".join(fields)


def make_sbp_qr(
    offer_id: int,
    user_tg_id: int,
    amount_rub: int,
) -> tuple[bytes, str]:
    """Сгенерировать PNG с банковским QR-кодом по ГОСТ Р 56042-2014.

    Возвращает ``(png_bytes, payload_str)``. ``payload_str`` — это
    содержимое QR в текстовом виде (для логов/диагностики, в чат
    показывать не обязательно).
    """
    purpose = f"Предоплата по офферу ETP-{offer_id:06d}"
    payload = _gost_qr_payload(amount_rub=amount_rub, purpose=purpose)
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
    """Сгенерировать PDF-счёт на предоплату. Возвращает байты PDF.

    Реквизиты получателя берутся из ``Settings.payee_*``.
    """
    st = get_settings()
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
        "Реквизиты для оплаты:",
        f"  Получатель: {st.payee_name}",
        f"  Режим налогообложения: {st.payee_tax_regime}",
        f"  ИНН: {st.payee_inn}",
        f"  Расч. счёт: {st.payee_account}",
        f"  Банк: {st.payee_bank_name}",
        f"  БИК: {st.payee_bik}",
        f"  Корр. счёт: {st.payee_corr_account}",
        f"  E-mail: {st.payee_email}",
        "",
        "Назначение платежа: предоплата по офферу ETP-"
        f"{offer_id:06d}.",
    ]
    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= line_h

    c.setFont(_REGISTERED_FONT, 9)
    c.drawString(
        2 * cm,
        2 * cm,
        "Документ сгенерирован автоматически era_etp_bot. Подпись не требуется.",
    )
    c.showPage()
    c.save()
    return buf.getvalue()
