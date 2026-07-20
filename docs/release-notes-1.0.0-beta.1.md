# Fieldnotes 1.0.0-beta.1 Release Notes

Date: July 18, 2026

## Major capabilities

- Local indexing for mixed course workspaces
- Grounded chat with citations
- Quiz flow with concept updates
- Notebook artifact persistence
- Source reopening by anchor
- Retrieval, planning, execution, observability tooling
- Portable Phase 0 and Phase 1 verification scripts
- Automatic fake-mode startup fallback when no `OPENAI_API_KEY` is present
- Real HTTP release verification through spawned `uvicorn`

## Known limitations

- Vector retrieval remains local-first baseline
- Frontend is desktop-first
- Release verification uses fake mode for offline smoke stability unless a real `OPENAI_API_KEY` is provided
- No desktop packaging bundle yet
- Windows sandbox now uses native Job Object containment for CPU time, memory, process count, and cleanup
- `npm install` currently reports audit findings that were not force-upgraded during beta because behavior-preserving fix path still needs review
- Release verification requires npm to be discoverable by the Python process that launches it

## Future roadmap

- Stronger semantic retrieval
- Richer notebook workflows
- Distribution hardening beyond beta
