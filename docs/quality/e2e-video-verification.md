# E2E video verification

This is a local-only Playwright recording harness. It uses a deterministic, synthetic Home conversation fixture; it does not call an API, use credentials, or collect personal data. The fixture is separate from the product runtime UI.

## Record WebM

```powershell
npx playwright install chromium
npx playwright test tests/e2e/video-verification.spec.js
```

Playwright writes the recorded `.webm` under `test-results/`. The HTML report is available with `npx playwright show-report`.

## Create MP4 (optional)

Install `ffmpeg` locally, then run:

```powershell
node scripts/convert-video-to-mp4.mjs test-results test-results/mp4
```

The converter only reads local `.webm` files and writes local `.mp4` files. Review the video before sharing; never include secrets, PII, or unapproved product screenshots, and do not automate posting to X or any external service.
