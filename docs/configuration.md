# Fieldnotes Configuration Reference

## Required

- `OPENAI_API_KEY`: required for live Responses API mode

## Optional

- `OPENAI_MODEL`: defaults to `gpt-5`
- `FIELDNOTES_USE_FAKE_LLM`: `1` enables deterministic internal LLM stub
- `FIELDNOTES_RETRIEVAL_PROVIDER`: `bm25 | hybrid | vector`
- `FIELDNOTES_EMBEDDINGS_PROVIDER`: `deterministic`
- `FIELDNOTES_EMBEDDING_MODEL`: defaults to `hash-v1`
- `FIELDNOTES_BM25_WEIGHT`
- `FIELDNOTES_VECTOR_WEIGHT`
- `FIELDNOTES_MAX_RETRIEVAL_CANDIDATES`
- `FIELDNOTES_MAX_CONTEXT_CHUNKS`
- `FIELDNOTES_MAX_CONTEXT_TOKENS`
- `FIELDNOTES_ENABLE_TRACING`
- `FIELDNOTES_ENABLE_METRICS`
- `FIELDNOTES_VERBOSE_TRACING`
- `VITE_API_BASE_URL`: optional frontend override; leave empty for default local Vite proxy workflow

## Startup validation

Startup validates:

- Responses API configuration
- Workspace registry write permission
- SQLite write access
- Sandbox availability
- Retrieval and embedding provider names

Expected missing-key error in live mode:

```text
Missing OPENAI_API_KEY.

Either:
1. export OPENAI_API_KEY=your_key
2. export FIELDNOTES_USE_FAKE_LLM=1
```

## Cross-platform notes

- Windows: sandbox runs without Unix `resource` limits
- macOS / Linux: sandbox applies CPU and memory limits
- Paths with spaces and Unicode are supported
