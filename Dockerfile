# Axial analyst service (issue #691): one image, two container roles --
# `uvicorn axial.service.api:app --factory` (the API, this image's default
# command) and `python -m axial.service.worker` (the worker, compose's own
# `command:` override on the same image) -- so a fix to the service layer
# never has to be built twice.
#
# `uv sync --group service` pulls in this image's actual need (FastAPI,
# psycopg, uvicorn, pyjwt, odfpy) on top of `dependencies`, which still
# carries the ingestion/pipeline stack (docling, unstructured-inference,
# ...) this image never runs -- `pyproject.toml` does not split ask-path
# deps from ingest-path deps, and splitting it is a bigger change than this
# issue's own scope (see the PR body's blast-radius note). The image is
# larger and slower to build than it needs to be; nothing on the ask path
# is missing or wrong.
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so an edit to src/ does not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --group service

COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev --group service

ENV PATH="/app/.venv/bin:${PATH}"

# `axial.query.names.find_names`' tier-4 semantic fallback loads its
# sentence-transformers encoder with `local_files_only=True` (that module's
# own docstring: construction must never reach the network mid-ask) -- so
# the model has to already be on disk. Pre-fetched here, once, at build
# time, for `axial.names.DEFAULT_MODEL_NAME`, the model this codebase's own
# embedding step uses unless an operator's `config/pipeline.yaml` names a
# different one -- a snapshot built against a different model needs that
# model baked in too (documented in docs/service-deployment.md).
RUN python -c "from axial.names import DEFAULT_MODEL_NAME; from sentence_transformers import SentenceTransformer; SentenceTransformer(DEFAULT_MODEL_NAME)"

EXPOSE 8000

CMD ["uvicorn", "axial.service.api:app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
