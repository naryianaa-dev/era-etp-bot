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

COPY pyproject.toml /app/
RUN pip install --upgrade pip \
    && pip install .

COPY bot /app/bot

RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/bot.sqlite3

CMD ["python", "-m", "bot.main"]
