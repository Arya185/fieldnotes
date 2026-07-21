# Deployment

Fieldnotes public demo target: single Render web service, single public URL, no authentication. This deployment is intentionally single-tenant and public-facing for judge review only. Do not treat it as hardened multi-user hosting.

## Why Render + one container

Use `Dockerfile.render` for public demo. It keeps backend and built frontend behind one host:

- nginx serves frontend and proxies API to local `uvicorn`
- same-origin requests avoid extra CORS / trusted-origin config
- bundled `demo_course/` lives inside same container at `/app/demo_course`
- Render readiness checks hit `/health`

Backend-only `Dockerfile` stays available. It now also copies `demo_course/` and respects `PORT`.

## Required files

- `Dockerfile.render`: full-stack image for Render
- `render.yaml`: Render Blueprint with `/health` readiness check
- `scripts/start_render.sh`: starts `uvicorn` and nginx in one container
- `frontend/nginx.render.conf.template`: nginx proxy config for Render

## Environment variables

Required for public fake-mode demo:

- `FIELDNOTES_USE_FAKE_LLM=1`

Optional for live OpenAI mode:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` default `gpt-5`
- `OPENAI_BASE_URL` empty for native OpenAI Responses API; set only for OpenAI-compatible endpoint overrides

Recommended low-cost thread caps:

- `OPENBLAS_NUM_THREADS=1`
- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`

Mode behavior:

- if `OPENAI_API_KEY` is absent, startup falls back to fake mode automatically
- if `OPENAI_API_KEY` is present, startup switches to live mode automatically
- `render.yaml` sets fake mode by default, so public redeploys stay cheap unless key is added

## First deploy on Render

1. Push branch with `Dockerfile.render`, `render.yaml`, and docs updates.
2. In Render, create new Blueprint from repository root.
3. Confirm service from `render.yaml` and deploy.
4. Leave `OPENAI_API_KEY` unset for default fake-mode public demo, or add it as secret before deploy if live mode needed.
5. Wait for Render health check on `/health` to pass.
6. Open public URL. Sidebar should already show `/app/demo_course`.
7. Click `Index Workspace`.
8. Ask questions against bundled sample course.

Judge flow does not require uploading files. Demo workspace is preloaded into image; browser only triggers indexing for `/app/demo_course`.

## Redeploy

Automatic redeploy:

1. Push commit to branch tracked by Render Blueprint.
2. Render rebuilds `Dockerfile.render`.
3. Render waits for `/health` to return `2xx` or `3xx` before routing traffic.

Manual redeploy:

1. Open Render service.
2. Click `Manual Deploy`.
3. Choose latest commit.

Environment-only change:

1. Open Render service `Environment`.
2. Add or update variable.
3. Use `Save and deploy` for runtime-only env changes like `OPENAI_API_KEY`.

## Local smoke run for deployment image

```bash
docker build -f Dockerfile.render -t fieldnotes-render .
docker run --rm -p 10000:10000 fieldnotes-render
```

Then open `http://127.0.0.1:10000` and confirm:

- frontend loads
- `GET /health` returns healthy payload
- workspace input defaults to `/app/demo_course`
- indexing and ask flow work in fake mode without `OPENAI_API_KEY`

## Scope warning

This deployment has no authentication, no tenant isolation, and no per-user workspace separation. Keep scope to short-lived public demo instance only.
