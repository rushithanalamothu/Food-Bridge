FROM ghcr.io/astral-sh/uv:0.11.10 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY config ./config
COPY scripts/seed_intake_demo.py ./scripts/seed_intake_demo.py
RUN uv sync --locked --no-dev
RUN useradd --create-home foodbridge
USER foodbridge
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "foodbridge.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
