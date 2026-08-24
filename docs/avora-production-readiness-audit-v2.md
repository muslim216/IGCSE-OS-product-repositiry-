# Avora — Production Readiness Audit v2

> **What this is.** The second independent production-readiness assessment, run against
> default `18d5052` (post PR #41 and the ~20 follow-up fix commits). It verifies what changed
> since the first audit, re-tests every prior finding against current code, and runs six
> specialist lenses (backend/security, frontend/a11y/perf, database/integrity, AI/cost,
> infrastructure/reliability, delta-verification) over the tree.
>
> **Method.** Read-only. Every finding cites file:line evidence at >80% confidence. Ground
> truth at audit time: backend 530 passed / 1 failed (the failure is the *untracked*
> `tests/test_ai_pricing 2.py` Finder-duplicate collecting stale expectations — not a real
> regression), frontend 181 passed, bundle 430 kB / 117.7 kB gz single chunk.
>
> **Written:** 24 August 2026.

---

## Executive verdict

**APPROVE WITH CONDITIONS** — mandatory before real students' coursework flows through the
system.

Nothing found is a breach or corruption in normal operation today (single-org reality, no real
traffic). But there are five independent, ordinary-day paths to losing or stranding real
student work, wrapped in an operations layer that would not notice any of them happening:

1. Every deploy landing while a marking job runs strands that job as `running` forever
   (`workers/jobs.py:188` — no startup reaper).
2. The uploads disk holding every submission image has no backup and no restore tool
   (`14-operations-runbooks.md` admits "There is no tool for this").
3. A tutor who alt-tabs mid-review loses unsaved marks — window-focus refetch overwrites
   drafts (`frontend/src/main.tsx:16` stock QueryClient + unguarded seed effects).
4. Adjusting a draft mark then letting the student resubmit throws a guaranteed FK
   `IntegrityError` and permanently wedges the submission (`mark_override_audit` FK has no
   cascade or guard; SQLite tests cannot see it).
5. An Anthropic brownout stalls the serial global worker ~10 min × retries per job — no SDK
   timeout is configured anywhere.

When these fire, nobody sees them: no logging configuration (the runbook itself records that
`log.info` lines are invisible in production), no request IDs, no error tracking, and nothing
polls `/health/ready`.

The engineering underneath is genuinely good — auth, upload validation, prompt governance,
query-level tenancy scoping, idempotent handlers, and the migration/deploy chain are
top-quartile. This is a strong codebase with an unfinished operational shell.

## Delta since audit v1

Exactly one prior finding fully closed (refresh token out of all response bodies — SEC-2, with
negative tests); one deliberately narrowed (review-queue `staleTime: Infinity` now documented
as traversal-ordering, bounded by queue-page refetch). Everything else remains open, and the
stock-palette count moved backwards (419 → ~473).

The owner's post-review fix commits were independently reviewed and verified sound, including
the auto-finalize scheme gate (`5b7cbe6`), the PROD-2 fabricated-zero repairs (`41e150d`,
`52b913e`), the localStorage session migration (`3faf39a`), and the sign-in race closure
(`389a7e9`). One inert inconsistency found: `DELIBERATELY_UNPRICED` in `test_ai_pricing.py`
contradicts the priced `.env.example` table two files away.

Phase 0 tasks **0.1–0.5 remain entirely unmerged** — five local-only branches. Consequence:
default still filters readiness v2 on `== finalized` (`readiness_v2.py:96,173,287`), so the
known scoring blindness is live, while its fix sits on `fix/av-29-settled-statuses`.

## Findings

### P1 (blockers for real users)

| # | Issue | Location | Fix | Effort |
|---|---|---|---|---|
| 1 | Uploads disk: no backup/restore; R13 never rehearsed | §08:404, §11:232 | Snapshot/S3 mirror + reconciliation + rehearsal | M-L |
| 2 | Orphaned `running` jobs unrecoverable except by manual SQL | `workers/jobs.py:176-193` | Startup reaper → `pending` (handlers idempotent, BE-6) | S |
| 3 | No logging config / request IDs / error tracking; `/health/ready` unpoll'd | `main.py`; §11:199-218 | logging config + request-id middleware + uptime poll (+ optional Sentry) | M |
| 4 | Refetch-clobber of unsaved work ×4 screens; Preferences mount race; silent save failures | `main.tsx:16`; `GradeBoundariesPage.tsx:45`; `PreferencesPage.tsx:100`; `TutorChatPage.tsx:31` | QueryClient defaults + dirty guards + onError | S |
| 5 | Resubmission FK wedge via `mark_override_audit` | `submissions.py:142-151`; `homework.py:261` | Guard resubmission when audit rows exist (409) | S |
| 6 | No SDK timeouts/retry caps on serial worker | `services/ai.py:142-167` | Explicit `timeout=`/`max_retries=` per surface | S |
| 7 | Admin bypasses organization scoping at ~12 sites incl. cross-tenant mark writes | `submissions.py:80` et al.; correct pattern at `today.py:36-41` | Extract shared `_org_scoped` helper; apply everywhere | M |
| 8 | Student-reachable AI endpoints unthrottled (`log_attempt`, `submit_work`) | `past_papers.py:278`; `submissions.py:105` | Per-student FixedWindowLimiter; cap re-log churn | S-M |
| 9 | Syllabus extraction spends tokens with zero metering | `syllabus_extraction.py` | `record_usage` + negative test | S |
| 10 | Whole upload read into RAM before size check | `storage.py:108-109` | Enforce limit on source bytes pre-decode | S |
| 11 | Merge task 0.1 so readiness sees auto-finalized marks | branch `fix/av-29-settled-statuses` | Push + PR the five Phase-0a branches | S |

### P2 (condensed)

Registration throttling · pricing/routing drift vs AV-124 (paste pricing into Render in the
same change as 3.2) · metering conditional skips & abandoned chat streams · chat history
unbounded resend · prompt-version stamp missed on bd97a88 (both sides read `v3`) ·
`apply_syllabus` lets any tutor rewrite the global subject tree · DB-12 drift (indexes in
migrations only) on `readiness_snapshots`/`factor_evaluations`/`evidence`/
`mark_override_audit` · `ai_usage_events` has zero indexes · N+1 clusters (review_queue 2N+1
unbounded, group assignments, analytics) · `api/readiness.py:121` fabricates `score=0.0`
(PROD-2 at contract level) · Submission/QuestionMark exactly-one-of CHECK constraints missing ·
`evidence.source_ref` lacks unique index · resubmission/file-delete orphan blobs on disk ·
engine pool defaults, no `pool_pre_ping` · `Assessment`/`Report` lack `organization_id` ·
QueryClient defaults · refresh-token single-flight mutex · Modal focus trap/restore/shared DOM
id · blank-screen trio (student Homework/Exams, tutor Mocks) · `ApiError.fields` consumed by
zero forms (0 `aria-invalid`, 0 `onBlur` repo-wide) · heading outline broken (no `<h1>`
anywhere; AppShell renders title as `<span>`) · hover-gated unnamed ✕ buttons ·
AssignmentDetail unconditional 5 s poll + unlabelled question-table inputs · JWT-default
fail-fast absent · `.env.example` missing `NARRATIVE_*` family + UPLOAD_DIR · CI lacks
coverage gate / CodeQL / pip-audit / npm audit / secret scan · no dependency lockfile (INF-12)
· no staging (DB-18 untested on real rows; migration 0012 class) · HSTS +
Permissions-Policy on vercel.json · Gemini thinking-token empty-parse (moot post-3.2).

### P3 (condensed)

403-vs-404 existence oracles (students/reports/assessments) · reports ignore org boundaries
(`reports.py:79`) · no refresh rotation/reuse detection · SYLLABUS prompt missing the
data-not-instructions clause · display names interpolated into system prompts · debounce
payload scans O(pending jobs) · `class_brief` sync-in-request · per-call Anthropic client (no
pooling) · unmemoized `QuestionCard` · legacy screens off-token (~473 stock classes) ·
AuthFile blob-revoke race · toast inconsistency · query errors rendered as permanent 404 copy ·
compose profile gaps (`GEMINI_API_KEY`, `REFRESH_COOKIE_SECURE=false`) · `# git test` comment
atop `main.py` · stale header-location comment · mypy scope ratchet pending for
`app.api`/`security.py` · **local `" 2"` Finder duplicates — delete them; one poisons local
pytest** · `DELIBERATELY_UNPRICED` vs priced-table contradiction.

## Verified clean (evidence-backed)

Tenancy scoping in queries derives from the authenticated user everywhere sampled;
`(organization, subject)` pair-scoping for students implemented correctly in
`past_papers._enrolled_scope` and `improvement._classmates`; API-20 polymorphic branch lives
exactly once; role-gate graph-walk test matches live routes; token type-checking, version
revocation, signed OAuth state, bcrypt anti-timing, single-use parent invites with atomic
consume; magic-byte upload validation with server-generated filenames and size-before-decode
on the non-UploadFile path; idempotent handlers with replace-not-append extraction and
never-overwrite-finalized marking; marks clamped, skipped questions never zeroed, readiness
pulled to ±10 of a deterministic reference with confidence damping; Markdown rendering builds
React nodes (no XSS sink); SQL parameterized throughout; secrets scan clean across history;
migration chain linear 0001→0023→0025 with working downgrades; boot-migration + liveness-gated
deploys correct; CI's generated-artifact freshness gate correctly ordered.

## Matrix

| Area | Score | Area | Score |
|---|---:|---|---:|
| Architecture | 72 | Scalability | 62 |
| Backend | 77 | Reliability | 60 |
| Frontend | 68 | Testing | 75 |
| Database | 66 | Deployment | 78 |
| Security | 74 | Observability | 35 |
| Privacy | 65 | Accessibility | 55 |
| AI | 78 | UX/Product | 72 |
| Performance | 70 | Documentation | 90 |
| Cost/FinOps | 70 | **Overall** | **70/100** |

## Cost model (configured prices)

Marking is >90% of modeled spend: booklet ≈100k input tokens resent per submission (Anthropic
cache TTL 5 min — different students' submissions hours apart never hit it). At 5 subs/student/
week: ~$1.3k/mo @100 students on opus-5 routing, **~$27k/mo @5,000 on sonnet-5, ~$66k on
opus-5**. Biggest levers in order: route marking to sonnet-5 (−58%); send only the
`question_range` pages or extend cache TTL during batches; batch-mark students per cached
booklet. Until AV-124/task 3.2 lands *with* Render-dashboard pricing, the dominant surface
records `cost_usd=NULL` — cost-blind exactly where spend concentrates.

## Final answers (compressed)

1. Production-ready today: **no** — conditions above. 2. Most dangerous: unprotected uploads
disk; deploy-stranded jobs; invisible failures. 3. Biggest architectural weakness: three
correctness mechanisms pinned to one instance by side effect. 4. Biggest security issue: admin
tenancy bypass (latent until an admin exists). 5. Biggest privacy concern: minors' work to AI
vendors with no documented DPA/retention — legal review required. 6. DB bottleneck:
`ai_usage_events`, then review-queue N+1. 7. Backend bottleneck: serial worker, no timeouts,
shared loop. 8. Frontend bottleneck: single chunk; draft-clobber bugs. 9. Scale bottleneck:
worker/disk/limiter triangle. 10. Reliability weakness: stranding + untested restores. 11.
Biggest AI risk: provider brownout ⇒ pipeline-wide stall. 12. Largest bill: unthrottled vision
marking loop, or opus-routing at scale. 13. Silent wrong data: readiness blind to
auto-finalized; fabricated `0.0`. 14. Cross-user exposure: admin bypass only. 15. Complete
outage: Postgres failover during boot-migration, or poisoned job behind green health checks.
16. Hardest recovery: uploads-disk loss. 17. Before 10 users: reaper, clobber fixes, FK guard,
SDK timeouts, size-before-read, delete `" 2"` files, uptime poll. 18. Before 100: backups +
rehearsal, logging/Sentry, throttles, merge 0.1–0.5, syllabus metering. 19. Before 1,000:
admin-rule unification, N+1 batching, usage indexes, lockfile+CodeQL, sonnet decision, staging
DB. 20. Can wait: code splitting, deeper a11y, token sweep, prompt v4 stamping, refresh
rotation. 21. Unverifiable: dashboard state, backup schedules, monitors, `sync:false` values,
disk trend. 22. External checks: R13 rehearsal, backup retention, `/health/ready` monitor,
redirect URI verbatim, privacy/DPA review. 23. Safe ceiling: tens now; ~100–200 after P1
quick-fixes; ~1k after the P2 batch. 24. Redesign now: make single-instance pinning an
explicit interface so Phase 1.3 is a swap. 25. Sign-off: not yet — *"after the six P1 fixes
ship and one restore rehearsal succeeds."*
