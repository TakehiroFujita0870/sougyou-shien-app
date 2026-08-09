# E2E video verification

This is a local-only Playwright recording harness. It opens the actual Vite application on a dedicated local port, seeds only a deterministic completed profile, and does not call an API, use credentials, or collect personal data.

## Desktop acceptance path

As a completed-profile desktop user, I want to turn a text conversation into an adopted project and inspect its Knowledge, so that the primary product loop stays demonstrably usable.

- Given: a reset local browser store and a synthetic completed profile.
- When: the user opens the 1440x900 Home surface, verifies the account popover and model selector, sends a text message, reloads, and adopts the restored proposal.
- Then: Project shows five decision views, Knowledge opens, and the browser has made zero `fetch` or `xhr` requests.

The test uses a dedicated Vite server at `127.0.0.1:4176`; it never reuses a developer preview. Playwright records WebM on every run and retains a trace when the scenario fails.

## Record WebM

```powershell
npx playwright install chromium
npx playwright test tests/e2e/video-verification.spec.js
```

Playwright writes the recorded `.webm` under `test-results/`. The HTML report is available with `npx playwright show-report`. Confirm that the artifact has a non-zero size before treating the recording as evidence.

## Create MP4 (optional)

Install `ffmpeg` locally, then run:

```powershell
node scripts/convert-video-to-mp4.mjs test-results test-results/mp4
```

The converter only reads local `.webm` files and writes local `.mp4` files. Review the video before sharing; never include secrets, PII, or unapproved product screenshots, and do not automate posting to X or any external service.
