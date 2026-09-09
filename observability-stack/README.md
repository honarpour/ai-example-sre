# Observability demo stack (Phase 7b)

A self-hosted Prometheus + Loki + GlitchTip stack, plus a toy "payments-api" service and a
concurrent load generator — not part of the AI SRE Investigator itself. This is the thing being
monitored, built purely to give `LiveObservabilitySource`
(`backend/app/sources/observability_live.py`) something real to query instead of a fixture.

The toy service deliberately mirrors the `bad-deploy` mock scenario
(`backend/app/fixtures/scenarios/bad_deploy.py`): `POST /admin/break` shrinks its simulated DB
connection pool live, under real concurrent load, reproducing the exact regression the mock
models — but with real Prometheus metrics, real Loki logs, and a real GlitchTip error group
instead of scripted fixture data.

## Why GlitchTip instead of Sentry

Official self-hosted Sentry is a ~13-container stack (Kafka, Clickhouse, Zookeeper, its own
Postgres/Redis) — disproportionate for a demo. GlitchTip implements Sentry's ingestion protocol
and a compatible Issues API at a fraction of the operational weight. Revisit real Sentry only if
this ever needs to demo against an org that already runs it.

## Prerequisites

Docker. If you don't have it: `brew install colima docker docker-compose && colima start`, then
remove any stale `credsStore` entry from `~/.docker/config.json` if you get a
`docker-credential-desktop: executable file not found` error (that value only makes sense with
Docker Desktop installed).

## Bring it up

```bash
cd observability-stack
docker compose up -d prometheus loki promtail grafana postgres redis glitchtip-migrate
docker compose up -d glitchtip glitchtip-worker
```

GlitchTip needs one-time setup (no API for the very first superuser):

```bash
docker compose exec -e DJANGO_SUPERUSER_EMAIL=admin@example.com \
  -e DJANGO_SUPERUSER_PASSWORD=admin12345 \
  glitchtip ./manage.py createsuperuser --noinput
```

Then in a browser at http://localhost:8001: log in, **Create New Organization** (any name, e.g.
`sre-demo`), **Create New Project** (platform: Python, name: `payments-api`, create a team when
prompted). Copy the project's DSN from its setup page — you'll need it for the next step.

Create `observability-stack/.env`:

```
GLITCHTIP_DSN=http://<public-key>@glitchtip:8000/1
```

(Note: `glitchtip:8000`, the docker-network hostname — not `localhost:8001`, which only resolves
from the host machine, not from inside the `demo-service` container.)

Create an API token (Profile → Auth Tokens) with `project:read`, `event:read`, `org:read`
scopes — needed by the backend to query the Issues API, not by the demo service itself.

Now bring up the demo service and load generator:

```bash
docker compose up -d --build demo-service load-generator
```

## Point the backend at it

In the **repo root** `.env` (not this directory's `.env` — different process):

```
OBSERVABILITY_DATA_SOURCE=live
PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100
GLITCHTIP_URL=http://localhost:8001
GLITCHTIP_API_TOKEN=<the token from above>
GLITCHTIP_ORG_SLUG=sre-demo
GLITCHTIP_PROJECT_SLUG=payments-api
```

GitHub stays mocked (`DATA_SOURCE=mock`, the default) — Phase 7a is deferred. Fire a `bad-deploy`
scenario alert from the UI: GitHub evidence (the PR, the commit, the deploy) comes from the mock
fixture as always; observability evidence (metrics, logs, error groups) comes from this real
stack. The two are deliberately telling the same story, since the demo service's `/admin/break`
mirrors bad-deploy's PR #4821 exactly.

## Trigger the incident for real

```bash
curl -X POST http://localhost:8010/admin/break -d '{"pool_size": 5}' -H 'Content-Type: application/json'
```

Wait ~15-30s for the load generator's concurrent traffic to actually exhaust the shrunk pool
(real 500s, a real GlitchTip issue, a real Prometheus error-rate spike), then fire an alert.
`POST /admin/restore` puts it back to a healthy pool size of 20.

## Useful endpoints while debugging

| What | Where |
|---|---|
| Demo service | http://localhost:8010 (`/healthz`, `/metrics`, `/charge`, `/admin/break`, `/admin/restore`) |
| Prometheus | http://localhost:9090 |
| Grafana (anonymous admin, for poking around — not queried by the backend) | http://localhost:3000 |
| Loki | http://localhost:3100 (no UI; query via API or Grafana) |
| GlitchTip | http://localhost:8001 |

## Tear down

```bash
docker compose down -v   # -v also removes the GlitchTip postgres volume
```
