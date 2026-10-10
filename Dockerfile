FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN useradd --create-home --uid 1000 user
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && chown -R user /app

USER user
ENV HOME=/home/user \
    PATH=/app/.venv/bin:$PATH \
    ANKI_CATALOG_HOST=0.0.0.0 \
    ANKI_CATALOG_PORT=7860

EXPOSE 7860
CMD ["anki-addons-catalog"]
