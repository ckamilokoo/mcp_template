FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-cache --no-dev
COPY main.py ./
EXPOSE 3000

CMD ["uv", "run", "uvicorn", "main:asgi_app", "--host", "0.0.0.0", "--port", "3000"]