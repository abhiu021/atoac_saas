FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# ws_hub keeps live negotiation state in memory, so this MUST run as a single
# worker (no --workers > 1, no horizontal autoscaling). uvicorn[standard] brings
# WebSocket support. $PORT is provided by the host (defaults to 8000 locally).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
