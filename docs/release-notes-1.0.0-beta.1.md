# Fieldnotes 1.0.0-beta.1 Release Notes

Date: July 18, 2026

## Major capabilities

- Local indexing for mixed course workspaces
- Grounded chat with citations
- Quiz flow with concept updates
- Notebook artifact persistence
- Source reopening by anchor
- Retrieval, planning, execution, observability tooling

## Known limitations

- Vector retrieval remains local-first baseline
- Frontend is desktop-first
- Release verification uses internal fake LLM mode for offline smoke stability
- No desktop packaging bundle yet
- Windows sandbox does not apply Unix `resource` limits
- `npm install` currently reports audit findings that were not force-upgraded during beta because behavior-preserving fix path still needs review

## Future roadmap

- Stronger semantic retrieval
- Richer notebook workflows
- Distribution hardening beyond beta
