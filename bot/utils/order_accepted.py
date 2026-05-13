"""Графика «ЗАКАЗ ПРИНЯТ В РАБОТУ» — генерируется через Pillow на лету.

Возвращает PNG-байты с тёмным градиентным фоном, крупной зелёной
«галочкой-чек» в круге и двумя строками текста: заголовок и сабтайтл
с номером заявки. Используется хендлерами ``car/parts/shop`` сразу
после фиксации заявки, чтобы:

  * показать клиенту явное визуальное подтверждение «всё ок, заявка
    принята в работу» (вместо текстового сообщения с inline-меню);
  * убрать необходимость держать inline-меню — после графики
    идёт пауза и «перезапуск» бота (см. ``_post_request.py``).

PIL-зависимость — уже в проекте (через ``qrcode`` → ``Pillow``),
поэтому отдельных пакетов добавлять не нужно. Если по какой-то
причине шрифт DejaVu отсутствует на хосте, мы корректно падаем
на ``ImageFont.load_default()``, чтобы Telegram всё равно получил
валидный PNG (только без кириллицы — это маловероятный сценарий).
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont


# Боевые шрифты на образах python:3.* slim есть в /usr/share/fonts.
# Берём DejaVu Sans Bold — он поддерживает кириллицу и хорошо смотрится
# крупным жирным заголовком.
_FONT_CANDIDATES_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_FONT_CANDIDATES_REG = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    """Возвращает (width, height) для строки текста."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _draw_vertical_gradient(
    img: Image.Image,
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> None:
    """Заливает Image вертикальным градиентом ``top → bottom``."""
    w, h = img.size
    px = img.load()
    if px is None:
        return
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)


def make_order_accepted_png(
    request_id: int,
    *,
    width: int = 1080,
    height: int = 720,
) -> bytes:
    """Сгенерировать PNG «ЗАКАЗ ПРИНЯТ В РАБОТУ» для заявки ``request_id``.

    Размер по умолчанию — 1080×720, это близко к 16:9 и нормально
    рендерится в Telegram как preview-картинка.

    Цветовая схема: тёмный градиент (графит → почти чёрный) + зелёный
    круг с белой галочкой по центру + светлый текст. Брендинг внизу.
    """
    bg_top = (16, 30, 24)        # тёмно-зелёный
    bg_bottom = (8, 12, 18)      # почти чёрный
    accent = (34, 197, 94)       # tailwind green-500
    accent_dark = (22, 163, 74)  # tailwind green-600
    fg = (245, 245, 245)
    muted = (160, 170, 178)

    img = Image.new("RGB", (width, height), bg_top)
    _draw_vertical_gradient(img, bg_top, bg_bottom)
    draw = ImageDraw.Draw(img)

    # ---- круг с галочкой (вверху по центру) ---- #
    circle_radius = int(min(width, height) * 0.18)
    cx = width // 2
    cy = int(height * 0.34)
    # внешнее «свечение» — лёгкий полупрозрачный круг побольше
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (
            cx - circle_radius - 24,
            cy - circle_radius - 24,
            cx + circle_radius + 24,
            cy + circle_radius + 24,
        ),
        fill=(34, 197, 94, 40),
    )
    img.paste(glow, (0, 0), glow)

    draw.ellipse(
        (cx - circle_radius, cy - circle_radius, cx + circle_radius, cy + circle_radius),
        fill=accent,
        outline=accent_dark,
        width=4,
    )
    # Галочка — ломаная линия из 3 точек.
    cw = int(circle_radius * 1.0)
    points = [
        (cx - cw // 2, cy + 4),
        (cx - cw // 8, cy + cw // 3),
        (cx + cw // 2, cy - cw // 3),
    ]
    draw.line(points, fill=fg, width=max(8, circle_radius // 12), joint="curve")

    # ---- заголовок ---- #
    title_font = _load_font(_FONT_CANDIDATES_BOLD, size=68)
    title = "ЗАКАЗ ПРИНЯТ В РАБОТУ"
    tw, th = _text_bbox(draw, title, title_font)
    title_y = cy + circle_radius + 50
    draw.text(((width - tw) // 2, title_y), title, font=title_font, fill=fg)

    # ---- сабтайтл с номером заявки ---- #
    sub_font = _load_font(_FONT_CANDIDATES_REG, size=36)
    sub = f"Заявка #{request_id} зарегистрирована"
    sw, sh = _text_bbox(draw, sub, sub_font)
    sub_y = title_y + th + 20
    draw.text(((width - sw) // 2, sub_y), sub, font=sub_font, fill=muted)

    # ---- брендинг внизу ---- #
    brand_font = _load_font(_FONT_CANDIDATES_BOLD, size=28)
    brand = "ERA  ETP"
    bw, bh = _text_bbox(draw, brand, brand_font)
    draw.text(((width - bw) // 2, height - bh - 36), brand, font=brand_font, fill=accent)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
