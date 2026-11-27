FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt
COPY --chown=65532:65532 . .
USER 65532:65532
EXPOSE 8080
CMD ["sh", "-c", "case ${WORKER_MODE:-pubsub} in outbox) app=render_app;; pubsub) app=push_app;; *) exit 2;; esac; exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 2 --timeout 105 \"$app:create_app()\""]
