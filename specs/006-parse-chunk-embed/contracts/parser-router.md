# Contract: Parser Router & Parsers

Internal contract (not an HTTP endpoint). The router maps a document's chosen source to a parser and
returns ordered typed chunks (FR-001–FR-004, FR-024, D8/D9).

## Source selection (FR-024 / D8)
`select_source(document_sources) -> chosen_source` for a multi-source document:
1. highest `SourceReliability.rank` (`regulatory_alert` > `peer_reviewed` > `preprint` >
   `case_report`);
2. tie-break: richest payload (longer serialized body / full-text source over abstract-only);
3. tie-break: most-recent `fetched_at`.
Exactly **one** payload is parsed; chunks are **never merged across sources**.

## Parser protocol
```
class Parser(Protocol):
    def parse(self, raw_payload: dict) -> list[ParsedChunk]: ...

@dataclass
class ParsedChunk:
    text: str            # non-empty after strip
    chunk_type: ChunkType
    section: str | None
    ordinal: int         # 0-based, assigned in emit order
```
`PARSERS: dict[SourceName, Parser]` registry; `route(source, raw_payload) -> list[ParsedChunk]`.
Unknown/unsupported source → raises a parse error classified **permanent** (FR-011).

## Per-source rules
| Source | Output |
|--------|--------|
| `pubmed` | abstract/section prose → `text` chunks tagged with section; MeSH/metadata captured (not a chunk) |
| `europepmc` | prose → `text` (section-tagged); each table → one `table` chunk (column headers repeated per row, **never split mid-row**); each figure caption → one `figure_caption` chunk |
| `openfda_faers` | one `structured_data` chunk: "Patient: <age>y <sex>. Drugs: …. Reactions: …. Outcome: …." |
| `openfda_label` | one chunk per label section, section name retained as `section` |
| `fda_medwatch` / `ema` / `mhra` | alert summary → one chunk; reliability `regulatory_alert` |

Every emitted chunk inherits the document's `source_reliability` at persist time (FR-007). Parsers
are pure (payload → chunks); no DB, no network, no embedding. Parsing then feeds the **chunker**
(FR-008) which sub-splits any oversized `text` chunk to the token cap before embedding.

## Failure semantics
- A structurally-invalid payload (cannot parse) → **permanent** parse error for that document
  (`errored_permanent`).
- A payload that parses but yields zero chunks → document marked `indexed_empty` (not an error).
