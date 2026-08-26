# NOTE: frontend is built on the host (pnpm build) because docker hub is not
# reachable from this machine; frontend/dist is copied in directly.
# If you have network access to docker hub, you can use the multi-stage variant below.

FROM python:3.12-slim
WORKDIR /app

# libffi for paramiko/cryptography, openssh-client for ssh-keyscan (optional convenience)
RUN apt-get update && apt-get install -y --no-install-recommends libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY frontend/dist ./static

ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/data
VOLUME /app/data
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
