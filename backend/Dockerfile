FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/fcsys /app/fcsys
COPY db/migrations /app/db/migrations
ARG CODE_VERSION=dev
ENV CODE_VERSION=${CODE_VERSION} MIGRATIONS_DIR=/app/db/migrations FILE_STORE=/data/files
RUN useradd -r -u 10001 app && mkdir -p /data/files && chown app /data/files
USER app
EXPOSE 8000
CMD ["uvicorn", "fcsys.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
