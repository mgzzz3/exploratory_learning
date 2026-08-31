FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ARG INSTALL_RESEARCH=true

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN if [ "${INSTALL_RESEARCH}" = "true" ]; then \
      pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" '.[research]'; \
    elif [ "${INSTALL_RESEARCH}" = "false" ]; then \
      pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" .; \
    else exit 1; fi

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
