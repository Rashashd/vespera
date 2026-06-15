# Pantera SPA

React 18 + Vite + TypeScript frontend for the Pantera pharmacovigilance platform.

## Prerequisites

Node 20 LTS, npm 10+.

## Development

```bash
# Install dependencies
npm ci

# Start dev server (API proxy to localhost:8000)
npm run dev
```

## Build

```bash
npm run build          # produces dist/
npm run preview        # serve dist/ locally on :5173
```

## Tests

```bash
npm test               # Vitest unit + component tests
npm run test:coverage  # with coverage report
npm run test:e2e       # Playwright e2e (requires live stack)
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend API origin |
| `PLAYWRIGHT_BASE_URL` | `http://localhost:5173` | Base URL for e2e tests |

## Docker

The `frontend` service in `docker-compose.yml` builds and serves the SPA on port 5173.
Configure `VITE_API_BASE_URL` as a build arg to point at the backend container.
