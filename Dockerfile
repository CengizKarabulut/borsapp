FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BORSAPP_REPOSITORY_ROOT=/app \
    BORSAPP_FINANCIAL_ARCHIVE=/app/financial_archive \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install --no-install-recommends --yes fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system borsapp \
    && useradd --system --gid borsapp borsapp
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY _legacy/taramabot ./_legacy/taramabot
COPY _legacy/ma-reaction-scanner ./_legacy/ma-reaction-scanner
COPY _legacy/market-telegram-suite ./_legacy/market-telegram-suite
COPY _legacy/tradingview-haber-botu ./_legacy/tradingview-haber-botu
RUN python -m pip install --no-cache-dir ".[runtime]"

COPY config ./config
COPY db ./db
COPY docs ./docs
RUN mkdir -p /app/runtime_artifacts /app/financial_archive \
    && chown -R borsapp:borsapp /app/runtime_artifacts /app/financial_archive

USER borsapp
ENTRYPOINT ["borsapp"]
CMD ["config-check"]
