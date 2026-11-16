# Nightly logical backup of the Neon database to Cloud Storage (Cloud Run job "barber-backup").
# pg_dump must be at least the server's major version (Neon runs Postgres 18).
FROM postgres:18-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY backup.sh /usr/local/bin/backup.sh
RUN chmod 755 /usr/local/bin/backup.sh
USER postgres
ENTRYPOINT ["/usr/local/bin/backup.sh"]
