FROM ghcr.io/astral-sh/uv:0.11.22-python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    STI_AUTO_CREATE_DATABASE=false
EXPOSE 8000
CMD ["sti-api"]
