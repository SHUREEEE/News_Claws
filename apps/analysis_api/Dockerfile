FROM python:3.12.8-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system newsclaws && useradd --system --gid newsclaws --home /app newsclaws
WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps/analysis_api ./apps/analysis_api
RUN python -m pip install --no-cache-dir "pip>=26.1.2,<27" \
    && pip install --no-cache-dir ".[extract,discover]"

COPY alembic.ini ./
COPY config ./config
COPY scripts ./scripts
RUN mkdir -p /data /backups \
    && chown -R newsclaws:newsclaws /app /data /backups

USER newsclaws
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"

CMD ["uvicorn", "news_claws.main:app", "--app-dir", "apps/analysis_api", "--host", "0.0.0.0", "--port", "8000"]
