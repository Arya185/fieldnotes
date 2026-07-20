# Fieldnotes Beta Known Issues

Version: `1.0.0-beta.1`

Only issues affecting correctness, data integrity, security, or installation should block `v1.0.0`.

## Critical

None confirmed.

## High

## Medium

### M-1. No packaged desktop installer

- Category: installation
- Reproducibility: always
- Impact: beta users must install Python and Node.js manually
- Workaround: follow [installation.md](installation.md)
- Planned fix: package distribution after beta validation
- Target release: post-`v1.0.0`
- Blocking status: no, if onboarding remains clear

### M-2. Offline smoke mode can be mistaken for full product evaluation

- Category: documentation
- Reproducibility: sometimes
- Impact: users may validate fake LLM mode instead of live answer quality
- Workaround: use live mode with `OPENAI_API_KEY` for product evaluation
- Planned fix: keep beta onboarding explicit about live mode versus smoke mode
- Target release: `v1.0.0`
- Blocking status: no

## Low

### L-1. `run.sh` is Unix-only

- Category: documentation
- Reproducibility: always on Windows
- Impact: Windows users cannot use convenience launcher
- Workaround: start backend with `python -m uvicorn ...` and frontend with `npm run dev`
- Planned fix: docs already clarified; no code change planned
- Target release: post-`v1.0.0`
- Blocking status: no

### L-2. Published docs lacked single external beta path

- Category: usability
- Reproducibility: always before beta onboarding doc
- Impact: users had to jump between README, installation guide, quickstart, and release notes
- Workaround: use [beta-onboarding.md](beta-onboarding.md)
- Planned fix: completed in beta program 1
- Target release: fixed in `1.0.0-beta.1`
- Blocking status: no

### L-3. Published docs mixed `python` and `python3`

- Category: documentation
- Reproducibility: always before wording cleanup
- Impact: cross-platform setup looked inconsistent
- Workaround: use `python` commands from onboarding and install docs
- Planned fix: completed in beta program 1
- Target release: fixed in `1.0.0-beta.1`
- Blocking status: no
