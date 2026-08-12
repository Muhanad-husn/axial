# Axial analyst service (issue #691): one image, two container roles --
# `uvicorn axial.service.api:app --factory` (the API, this image's default
# command) and `python -m axial.service.worker` (the worker, compose's own
# `command:` override on the same image) -- so a fix to the service layer
# never has to be built twice.
#
# `uv sync --no-default-groups --group service` (issue #772) pulls in only
# this image's actual need (FastAPI, psycopg, uvicorn, pyjwt, odfpy,
# lancedb, sentence-transformers) -- `pyproject.toml` now splits the
# ask-path deps `service` names from the ingest-path stack (docling,
# unstructured[-inference], the two Google packages), which lives in its
# own `ingest` dependency group and never ships in this image. CPU-only
# torch (`[tool.uv.sources]`, Linux-only marker): the default PyPI wheel
# bundles ~4GB of CUDA runtime this container has no GPU to use.
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uv

WORKDIR /app

# No wheel/build cache left in the image layers -- this container never
# rebuilds itself, so there is nothing here for a cache to speed up.
ENV UV_NO_CACHE=1

# Pinned explicitly (issue #772) rather than left to the default-HOME
# convention, so the pre-fetch below and the served process agree on the
# same cache directory even if a later change (a non-root USER, a
# different base image) would otherwise move $HOME between build and run.
ENV HF_HOME=/app/.cache/huggingface

# Dependencies first, so an edit to src/ does not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-default-groups --group service

# Needed before the pre-fetch below: `python -c` has to resolve the venv
# `uv sync` just populated (sentence-transformers included), not the base
# image's own interpreter.
ENV PATH="/app/.venv/bin:${PATH}"

# `axial.query.names.find_names`'s tier-4 semantic fallback and
# `axial.argmap.build`'s own encoder both load a sentence-transformers
# model with the network refused at ask time (`local_files_only=True`, and
# the `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` env set below) -- so the
# weights have to already be on disk before either ever runs. Pre-fetched
# here, once, at build time, for the encoder these two modules already
# agree on (`axial.names.DEFAULT_MODEL_NAME` ==
# `axial.argmap.build.ENCODER_MODEL`) -- a snapshot built against a
# different model needs that model baked into a custom image instead
# (documented in docs/service-deployment.md).
#
# Only `src/axial/names.py` is copied here, not the rest of `src/` -- the
# constant is read out of its source TEXT, not imported: `axial.names`
# itself imports `axial.chunk`/`axial.extract`/`axial.interrogate`, which
# need the rest of the package tree present to import at all, and copying
# that much here would give this layer nearly the same cache key as the
# full `COPY src ./src` below, defeating the point of hoisting it. This
# keeps the layer's cache key to the one file that can invalidate it.
COPY src/axial/names.py ./src/axial/names.py
RUN python -c 'import pathlib, re; from sentence_transformers import SentenceTransformer; text = pathlib.Path("src/axial/names.py").read_text(encoding="utf-8"); model_name = re.search(r"^DEFAULT_MODEL_NAME = \"([^\"]+)\"", text, re.M).group(1); SentenceTransformer(model_name)'

# Set only after the pre-fetch above, which needs the network -- from here
# on, a served ask (or a startup that needs the encoder and finds no cache)
# fails loudly instead of silently reaching huggingface.co mid-ask.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-default-groups --group service

EXPOSE 8000

CMD ["uvicorn", "axial.service.api:app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
