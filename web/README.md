# DeepDesk Web

The Vue 3 frontend for DeepDesk, an agentic workspace for research and knowledge work.

## Requirements

- Node.js 20+
- Backend available on `http://127.0.0.1:8888` for local development

## Development

```bash
npm install
npm run dev
```

The Vite development server uses `/api` as a local proxy to `http://127.0.0.1:8888`, so the backend does not need a frontend-specific CORS change for local development.

## Environment

Create `.env.local` only when you need to override defaults:

```env
VITE_API_BASE_URL=/api
VITE_API_KEY=
```

`VITE_API_KEY` is optional. It is only needed when the backend enables Bearer API key authentication. The same value can also be saved from the in-app Settings dialog.

For a deployed frontend, set `VITE_API_BASE_URL` to the public backend base URL or configure the hosting layer to proxy `/api`.

## Checks

```bash
npm run test
npm run typecheck
npm run lint
npm run build
npm run e2e
```

Browser E2E tests live in `e2e/browser.spec.ts`. The default Playwright command uses the bundled Chromium browser after `npx playwright install chromium`. On Windows, an installed Edge can be reused instead:

```powershell
$env:PLAYWRIGHT_CHANNEL="msedge"
npm run e2e
```
