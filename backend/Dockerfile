# One image for api, bot and worker (different commands in compose).
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# dependencies first: this layer is cached until pyproject.toml changes
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y barber-backend
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-deps .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENV=production \
    LOG_JSON=true \
    MEDIA_DIR=/data/media
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data/media && chown app:app /data/media
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /src/alembic ./alembic
COPY --from=build /src/alembic.ini ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)" || exit 1
# api by default; compose overrides the command for bot / worker / migrate
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "2", "--no-server-header"]
