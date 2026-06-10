"""Enum definitions for the embedding module."""

from enum import StrEnum


class ChunkType(StrEnum):
    """Chunk type classification (FR-002)."""

    TEXT = "text"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    STRUCTURED_DATA = "structured_data"


class DocumentIndexStatus(StrEnum):
    """Document indexing status (FR-010/FR-011)."""

    NOT_INDEXED = "not_indexed"
    INDEXED = "indexed"
    INDEXED_EMPTY = "indexed_empty"
    ERRORED_TRANSIENT = "errored_transient"
    ERRORED_PERMANENT = "errored_permanent"


class IndexBuildRunStatus(StrEnum):
    """Index build run outcome status."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
