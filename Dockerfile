FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BORSAPP_REPOSITORY_ROOT=/app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system borsapp \
    && useradd --system --gid borsapp borsapp
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY _legacy/market-telegram-suite ./_legacy/market-telegram-suite
COPY _legacy/tradingview-haber-botu ./_legacy/tradingview-haber-botu
RUN python -m pip install --no-cache-dir ".[runtime]"

COPY config ./config
COPY db ./db
COPY docs ./docs
RUN mkdir -p /app/runtime_artifacts && chown -R borsapp:borsapp /app/runtime_artifacts

USER borsapp
ENTRYPOINT ["borsapp"]
CMD ["config-check"]
