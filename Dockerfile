FROM python:3.11-slim

WORKDIR /app
COPY allocopt ./allocopt
COPY tests ./tests
RUN pip install --no-cache-dir numpy pytest

# Deterministic, synthetic-only CLI; no market data is fetched.
ENTRYPOINT ["python", "-m", "allocopt.cli"]
