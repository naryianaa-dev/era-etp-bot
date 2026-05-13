FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# кириллический шрифт для счётов-PDF
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the package source before `pip install .` — newer pip resolves package
# dirs eagerly during wheel build, so `bot/` and README.md must exist.
COPY pyproject.toml README.md /app/
COPY bot /app/bot

RUN pip install --upgrade pip \
    && pip install .

RUN mkdir -p /app/data

ENV DB_PATH=/app/data/bot.sqlite3

CMD ["python", "-m", "bot.main"]
