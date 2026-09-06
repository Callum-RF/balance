# Balance — self-host image. Single process (FastAPI API + NiceGUI UI) on :8000.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached until requirements change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code only (data/, venv/, tests/, docs/ are excluded — see .dockerignore).
COPY backend/ backend/
COPY frontend/ frontend/
COPY run.py .

# BALANCE_HOST must be 0.0.0.0 in a container so the mapped port is reachable
# (run.py defaults to 127.0.0.1 for the bare-metal/Tailscale setup).
ENV BALANCE_HOST=0.0.0.0 \
    BALANCE_PORT=8000 \
    PYTHONUNBUFFERED=1

# SQLite DB, receipts and the storage secret live here — mount a volume to persist.
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["python", "run.py"]
