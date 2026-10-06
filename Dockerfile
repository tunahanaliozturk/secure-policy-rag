# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv

FROM python:3.14-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
# The embedding model is part of the image, so a running container never downloads anything.
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')" \
    && chmod -R a+rX /models

FROM python:3.14-slim-trixie
# Take distribution security fixes released after the base image was built. Nothing is installed at run time, so pip
# leaves the image. The service runs as an unprivileged user that owns nothing it executes.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --quiet pip \
    && useradd --system --uid 10001 --home-dir /app spr
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /models /models
COPY corpus ./corpus
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SPR_MODEL_CACHE_DIR=/models \
    HF_HUB_OFFLINE=1
USER spr
EXPOSE 8000
ENTRYPOINT ["spr"]
# 0.0.0.0 inside the container only; compose publishes the port on 127.0.0.1 of the host.
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
