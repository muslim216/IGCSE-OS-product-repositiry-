# ADR-0001 — One deployable API, not microservices

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

Avora spans six product surfaces — Student CRM, Lessons, Readiness, Knowledge Base,
Homework, Reports — plus AI integration, file storage, background processing, and two
external integrations. That surface count invites decomposition: readiness computation looks
like a service, marking looks like a service, Classroom sync looks like a service.

The system serves a single-tutor product. The entire backend is roughly 12,400 lines of
Python.

## Decision

Avora is **one FastAPI application** (`backend/app/`) deployed as one Render service, and
one React application deployed on Vercel. There is no service mesh, no inter-service RPC,
and no per-domain deployable.

Module boundaries are enforced by layering — `api/ → services/ → models/` — not by process
boundaries. `services/` modules are the units that would become services if decomposition
were ever warranted, and they are already separated along those lines.

## Alternatives considered

**Microservices per domain.** Would buy independent deployment and independent scaling. It
would cost network failure modes between every pair of collaborating domains, distributed
transactions where marking updates evidence which updates readiness, deployment
coordination, and per-service observability that this project does not have for one service
yet. The scaling it buys is not needed: the current constraint is a single instance for
entirely different reasons (see ADR-0002 and RISK-1).

**A separate worker service.** Genuinely reasonable, and partially anticipated — the job
table already claims with `FOR UPDATE SKIP LOCKED`, which is exactly what multiple worker
processes need. Rejected for now only because the API is pinned to one instance anyway; this
is the first decomposition to make when that changes.

**Serverless functions.** Would fit the request/response surfaces but not the long-running
AI jobs, which routinely exceed function timeouts, and not the persistent upload disk.

## Consequences

**Easier:** one deploy, one log stream, one set of credentials, one database connection
pool. A change spanning marking and readiness is one commit and one release. Local
development is `uvicorn` plus `npm run dev`.

**Harder:** no independent scaling — a heavy extraction job competes with request serving in
the same process (see §10). No independent deployment: a frontend-only fix still redeploys
nothing, but a backend typo redeploys everything. Nothing enforces the layering, so the
module boundaries survive on convention alone (`GOV-7`).

**Permanently more expensive:** extracting a service later means extracting it from code
that had no reason to keep the boundary clean. The layering discipline is what keeps that
cost bounded, which is why `GOV-7` is Critical.

## Revisit when

A single subsystem's resource profile genuinely conflicts with the rest — document
processing needing GPUs, or an order-of-magnitude memory difference. Extract that one thing.
The worker is the named first candidate.
