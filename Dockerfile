FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY . .
RUN uv sync --locked

RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]

EXPOSE 8000