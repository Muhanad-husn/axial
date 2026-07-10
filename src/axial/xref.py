"""Cross-reference detection: for each prose chunk, one LLM call decides
which (if any) of the source's real artifacts (tables or figures) the
chunk's prose text references (e.g. "as Table 3 shows") (PRD §5 stage 7,
§7.2, §8 P0-7).

This pass never invents a second chunk-id or artifact-id scheme: it reuses
`axial.chunk.run_chunk` for the chunk records and `axial.artifacts.run_artifacts`
for the source's real artifact records, so the pairs it emits are usable as a
graph over the system's real, addressable chunk/artifact records. A
referenced artifact_id absent from the source's real artifact set produces no
pair -- a dangling link is filtered, not emitted (PRD §8 P0-7). This slice
emits xref pairs to stdout only; writing bidirectional backlinks into vault
notes' frontmatter is slice 02.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from axial.artifacts import (
    ArtifactsError,
    DEFAULT_DOMAIN_DIR,
    run_artifacts,
)
from axial.chunk import ChunkError, run_chunk
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    LLMError,
    XREF_PASS_NAME,
    get_client,
)

_XREF_PROMPT_TEMPLATE = """\
You are deciding which, if any, of the source's known artifacts (tables or \
figures) the CHUNK below explicitly references (e.g. "as Table 3 shows"). \
Respond with ONLY a JSON object (no prose, no markdown fences) with exactly \
one key, "referenced_artifact_ids": a JSON array of artifact_id strings \
drawn from the list below that this chunk references (an empty array if \
none).

Known artifacts:

{artifact_ids}

Chunk:

{chunk_text}
"""

_NO_ARTIFACTS_PLACEHOLDER = "(none)"


class XrefError(Exception):
    """Base class for all cross-reference-detection errors."""


class MissingSourceError(XrefError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkingFailedError(XrefError):
    """Raised when the underlying chunking pass (`run_chunk`) fails."""

    def __init__(self, cause: ChunkError):
        self.cause = cause
        super().__init__(str(cause))


class ArtifactsFailedError(XrefError):
    """Raised when the underlying artifact-classification pass
    (`run_artifacts`) fails."""

    def __init__(self, cause: ArtifactsError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(XrefError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails, so the CLI renders a clean `error: ...` instead of a
    bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class XrefParseError(XrefError):
    """Raised when the model's xref response is not parseable into a list of
    referenced artifact_id strings."""


def compose_xref_prompt(chunk_text: str, artifact_ids: list[str]) -> str:
    """Compose the xref-detection prompt from the chunk's own text and the
    source's real, known artifact ids -- never a hardcoded list."""
    ids_block = (
        "\n".join(f"- {artifact_id}" for artifact_id in artifact_ids)
        if artifact_ids
        else _NO_ARTIFACTS_PLACEHOLDER
    )
    return _XREF_PROMPT_TEMPLATE.format(artifact_ids=ids_block, chunk_text=chunk_text)


def parse_referenced_artifact_ids(raw: str) -> list[str]:
    """Parse the model's raw xref response into a list of referenced
    artifact_id strings. Accepts a top-level object with a
    "referenced_artifact_ids" key, or a bare top-level array."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise XrefParseError(f"model response was not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        if "referenced_artifact_ids" not in data:
            raise XrefParseError(
                f"expected a top-level 'referenced_artifact_ids' key, got "
                f"keys: {sorted(data.keys())}"
            )
        ids = data["referenced_artifact_ids"]
    else:
        ids = data

    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise XrefParseError(
            f"expected referenced artifact ids to be a JSON array of strings, got {ids!r}"
        )
    return ids


def build_xref_pairs(
    chunk_id: str, referenced_ids: list[str], known_artifact_ids: set[str]
) -> list[dict[str, str]]:
    """Assemble `{"chunk_id": ..., "artifact_id": ...}` pairs for `chunk_id`,
    filtering `referenced_ids` against `known_artifact_ids` -- an id not
    among the source's real artifacts (a dangling link) produces no pair
    (PRD §8 P0-7)."""
    return [
        {"chunk_id": chunk_id, "artifact_id": artifact_id}
        for artifact_id in referenced_ids
        if artifact_id in known_artifact_ids
    ]


def run_xref(
    source_path: str | Path,
    client: LLMClient | None = None,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    chunks_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the cross-reference-detection pass on `source_path`.

    Reuses `run_chunk` for chunk records and `run_artifacts` for the
    source's real artifact records (never a parallel id scheme for either).
    For each chunk, calls the LLM once (`pass_name="xref"`) with the chunk
    text and the source's known artifact ids, then filters the parsed
    referenced ids against the real artifact-id set before emitting pairs --
    a referenced id absent from that set (a dangling link) yields no pair.
    """
    path = Path(source_path)
    try:
        compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    if client is None:
        try:
            client = get_client(config_path=config_path)
        except LLMError as exc:
            raise LLMFailedError(exc) from exc

    try:
        chunk_records = run_chunk(
            path,
            client=client,
            envelopes_dir=envelopes_dir,
            config_path=config_path,
            chunks_dir=chunks_dir,
        )
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc

    try:
        artifact_records = run_artifacts(
            path, client=client, domain_dir=domain_dir, config_path=config_path
        )
    except ArtifactsError as exc:
        raise ArtifactsFailedError(exc) from exc

    known_artifact_ids = {record["artifact_id"] for record in artifact_records}
    artifact_id_list = sorted(known_artifact_ids)

    pairs: list[dict[str, Any]] = []
    for chunk in chunk_records:
        prompt = compose_xref_prompt(chunk["text"], artifact_id_list)

        try:
            raw_response = complete_json(client, prompt, pass_name=XREF_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc
        except ModelJsonError as exc:
            raise XrefParseError(f"model response was not valid JSON: {exc}") from exc

        referenced_ids = parse_referenced_artifact_ids(raw_response)
        pairs.extend(build_xref_pairs(chunk["chunk_id"], referenced_ids, known_artifact_ids))

    return pairs
