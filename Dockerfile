FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    FORWARDED_ALLOW_IPS="*" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# uvicorn's own request log is off; the app writes its own JSON request log.
# exec makes uvicorn the main process, so it gets Render's stop signal and shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
