# era_etp_bot — Telegram-бот электронной торговой площадки

Бот на **Python 3.12** и **aiogram 3.x** с полноценной FSM-логикой, тремя диалоговыми ветками
(автомобиль / запчасти / покупки), встроенной мини-админкой прямо в Telegram и mock-оплатой
через СБП-QR и PDF-счёт.

## Что умеет

### Для пользователя
- `/start` — знакомство (спрашивает имя, сохраняет в БД).
- Главное меню с тремя ветками:
  - **🚗 Автомобиль**: марка → модель → мин. год → привод → коробка → пробег → дилер/аукцион.
    - *Дилер*: выбор способа оплаты (СБП / Счёт).
    - *Аукцион*: описание повреждений → максимальная ставка USD → оплата.
  - **🔧 Запчасти**: марка → модель → год → VIN → деталь.
    Если артикул неизвестен — опционально принимает фото детали.
  - **🛒 Покупки**: название → URL → комментарии.
- **«Мои заявки»** — последние 20 своих заявок.
- В любой момент диалога работают кнопки **↩️ Назад** и **✖️ Отмена**.

### Для админа
- Автоматические пуши **в тот же Telegram** при каждой новой заявке пользователя
  (с inline-кнопкой «📨 Создать оффер»).
- Команды:
  - `/inbox` — все заявки (последние 50).
  - `/inbox_new` — только необработанные.
  - `/request <id>` или `/request_<id>` — карточка заявки + действия.
  - `/offer <user_tg_id> [сумма_руб]` — создать оффер (запустит FSM).
  - `/stats` — сводка.
- Через кнопку «📨 Создать оффер» — пошагово: название → описание → сумма → оффер улетает
  пользователю с inline-кнопками **[Сделать выбор]** / **[Отклонить]**.

### Поток оплаты
- Приняв оффер, пользователь выбирает способ оплаты.
- Бот считает предоплату: **15 %** от суммы, но **не меньше 100 000 ₽**
  (настраивается через `PREPAY_PCT` / `PREPAY_MIN_RUB`).
- **СБП**: генерирует PNG с QR (mock `qr.nspk.ru`-ссылка).
- **Счёт**: генерирует PDF с реквизитами-заглушками (ReportLab, шрифт DejaVu).
- Админ получает пуш «пользователь X выбрал оплату Y по офферу #Z».

## Стек

| Компонент | Версия |
|-----------|--------|
| Python | 3.12 |
| aiogram | 3.13+ |
| БД | SQLite (через SQLAlchemy 2.0 async + aiosqlite) |
| Конфиг | pydantic-settings |
| PDF | ReportLab |
| QR | qrcode[pil] |
| Валидаторы | `validators` для URL |

## Запуск локально

```bash
# 1. Клон + окружение
git clone https://github.com/naryianaa-dev/era-etp-bot.git
cd era-etp-bot
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# 2. Настройка
cp .env.example .env
# впиши BOT_TOKEN от @BotFather и свой tg id в ADMIN_IDS

# 3. Старт
python -m bot.main
```

## Запуск через Docker

```bash
cp .env.example .env   # впиши BOT_TOKEN и ADMIN_IDS
docker compose up --build -d
docker compose logs -f
```

SQLite-файл лежит в `./data/bot.sqlite3` (volume-маунт), сохраняется между рестартами.

## Деплой на Fly.io (бесплатно)

```bash
# 1. Установить fly CLI → https://fly.io/docs/hands-on/install-flyctl/
# 2. Залогиниться
fly auth login

# 3. Инициализация (создаст app с именем, которое ты выберешь)
fly launch --no-deploy --copy-config

# 4. Volume для SQLite (1 GB бесплатно)
fly volumes create data --size 1 --region fra

# 5. Секреты
fly secrets set BOT_TOKEN=0000000000:AAA... ADMIN_IDS=123456789

# 6. Выкатка
fly deploy
```

Бот работает в long-polling — HTTP-порт открывать не нужно, `fly.toml` уже настроен.

## Структура проекта

```
bot/
├── main.py                # entry point, регистрирует роутеры
├── config.py              # pydantic-settings (BOT_TOKEN, ADMIN_IDS, ...)
├── db.py                  # SQLAlchemy модели (User, Request, Offer)
├── states.py              # FSM-группы состояний для всех веток
├── keyboards.py           # Inline/Reply-клавиатуры
├── notify.py              # форматирование заявок, уведомления админам
├── utils/
│   ├── validators.py      # parse_year, parse_mileage, VIN, URL
│   └── payments.py        # compute_prepayment, make_sbp_qr, make_invoice_pdf
└── handlers/
    ├── common.py          # /cancel, /back
    ├── start.py           # /start, /menu, «Мои заявки»
    ├── car.py             # ветка «Автомобиль»
    ├── parts.py           # ветка «Запчасти»
    ├── shop.py            # ветка «Покупки»
    └── admin.py           # /inbox, /offer, обработка «Сделать выбор», оплата
```

## ENV-переменные

| Имя | Пример | По умолчанию | Описание |
|-----|--------|--------------|----------|
| `BOT_TOKEN` | `6123...AAA` | **обязательно** | Токен от @BotFather |
| `ADMIN_IDS` | `123456789` | пусто | Список tg id через запятую |
| `DB_PATH` | `./data/bot.sqlite3` | `./data/bot.sqlite3` | Путь к SQLite-файлу |
| `PREPAY_MIN_RUB` | `100000` | `100000` | Минимум предоплаты, ₽ |
| `PREPAY_PCT` | `15` | `15` | % предоплаты |
| `LOG_LEVEL` | `INFO` | `INFO` | Python logging level |

## Разработка

```bash
# Линтер
ruff check .

# Типы
mypy bot

# Тесты (если добавишь)
pytest
```

## Лицензия

Внутренний проект. Использование и распространение — по согласованию с владельцем.
