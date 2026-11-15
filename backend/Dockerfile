# One image for api, bot and worker; the role is the first argument (docker-entrypoint.sh).
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
# executable bit comes from git (no --chmod: Cloud Build's default builder lacks BuildKit)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health/live' % os.environ.get('PORT','8000'), timeout=2)" || exit 1
ENTRYPOINT ["docker-entrypoint.sh"]
# role: api (default) | bot | worker | worker-http | migrate
CMD ["api"]
