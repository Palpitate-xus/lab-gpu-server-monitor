# NOTE: frontend is built on the host (pnpm build) because docker hub is not
# reachable from this machine; frontend/dist is copied in directly.
# If you have network access to docker hub, you can use the multi-stage variant below.

FROM python:3.12-slim
WORKDIR /app

# libffi for paramiko/cryptography; ipmitool for the out-of-band IPMI tier
RUN apt-get update && apt-get install -y --no-install-recommends libffi-dev ipmitool \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 10001 appuser
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY frontend/dist ./static
RUN chown -R appuser:appuser /app

ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/data && chown -R appuser:appuser /app
VOLUME /app/data
EXPOSE 8000

USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;op=urllib.request.build_opener(urllib.request.ProxyHandler({}));r=op.open('http://127.0.0.1:8000/api/health',timeout=3);exit(0 if r.status==200 else 1)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
