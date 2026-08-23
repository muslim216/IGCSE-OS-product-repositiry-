# Avora New State Plan — handoff through task 0.10

> **What this is.** A handoff written at the point tasks `0.6`–`0.10` of
> `docs/avora-new-state-august-16.md` are complete and committed, finishing Phase 0. Read it
> together with its predecessor, `docs/avora-new-state-plan-till-0.5.md`, which covers `0.0`–
> `0.5` and whose standing instructions remain in force.
>
> **Status at handoff:** six commits on five stacked branches plus this document, all cut from
> the `0.5` docs branch. **None merged. Pushed 23 Aug; rebased onto the default branch after PRs #34/#35 landed** (the SEC-2 refresh-token change reshaped `TokenPair`, the tutor fixture and the tripwire — `0.8`'s OpenAPI artefacts were regenerated, `0.9` gained a one-line follow-up commit). The merge
> button is the owner's.
>
> **Written:** 23 August 2026.

---

## 1. The one-paragraph version

Phase 0 is done. Tasks `0.6`–`0.10` — the Avora rename, per-user time zones, a Python type
checker with generated API types, the token-revocation tripwire, and the AI price table — are
built, tested and committed, one branch per task as before. Unlike `0.1`–`0.5`'s six independent
branches, these five are **stacked in a single line**, so merging their PRs in order replays
exactly what was tested. Backend went from 498 to 506 passing, frontend held at 161, and the
repo gained its first Python type-check gate (`mypy`, zero errors across `app.services` +
`app.schemas`) and its first generated frontend API contract. Nothing is merged or pushed, so
production is exactly where it was.

---

## 2. Branch inventory

The stack roots on `docs/avora-handoff-through-0.5` (`8793f50` — the plan, the constitution
updates and the `0.5` handoff), which itself waits on the default branch
(`claude/igcse-os-planning-q8be0t`, still awaiting the GitHub rename).

| Task | Branch | Head | Files | Suite at commit |
|---|---|---|---|---|
| — | `docs/avora-handoff-through-0.5` | `8793f50` | 13 | docs only |
| `0.6` | `feat/av-4-rename-avora` | `48d83b3` | 59 | backend 498 · frontend 161 |
| `0.7` | `feat/av-67-user-timezone` | `66580a4` | 13 | backend 502 · frontend 161 |
| `0.8` | `feat/av-79-type-safety` | `dfe88dc` | 27 | backend 502 · frontend 161 · **mypy 0 errors** |
| `0.9` | `feat/f8-token-revocation-tripwire` | `1ed8bea` | 2 | backend 503 |
| `0.10` | `feat/av-2-ai-pricing` | `b20a369` | 3 | backend 506 · frontend 161 |
| — | `docs/handoff-through-0.10` | *(this file)* | 1 | docs only |

**Merge order is the stack order.** Each branch contains the ones above it, so PRs must be
opened and merged top-down: `0.6` first, then `0.7`, … `0.10`. Merging out of order still works
(GitHub sees supersets), but reviewing against the stacked bases shows each PR as exactly one
task's diff.

**Interaction with the unmerged `0.1`–`0.5` branches.** This stack does not contain them, and
they do not contain it. Expect textual (not semantic) conflicts when both lines eventually meet
on the default branch: `conftest.py`, `test_authorization.py` and `CLAUDE.md` are edited by
both `0.5` and `0.6`. One ordering constraint is real: **migration `0025_user_time_zone`
(`0.7`) chains from `0023`**, written before knowing whether `0024_drop_chat` (`0.3`) merges
first. If `0.3` lands first, rebase `0025` onto `0024` — the file carries a comment saying so.

---

## 3. What each task actually did

### 0.6 — Rename MANARA / IGCSE-OS → Avora *(AV-4, E10)*

One mechanical sweep plus a handful of deliberate manual edits. `git mv
docs/manara-architecture.md → docs/avora-architecture.md`; a repo-wide rename across ~58 files
covering user-facing strings, docstrings, README, CLAUDE.md, seed copy and documentation
cross-references; then by hand: `config.py`'s `app_name`, both package names
(`avora-backend`, `avora-frontend`), and `pyproject.toml`'s description.

**Deliberately untouched:** the Render hostname `igcse-os-api.onrender.com` (referenced by
`frontend/vercel.json` and the OAuth redirect chain), the GitHub repository name, and the
default-branch literal in `ci.yml`'s trigger list. All three are deployment identifiers the
owner changes manually; renaming them in code would break a deploy that has not been renamed
yet. **Historical audit documents were excluded** — they describe the product as it was named
at the time, and rewriting them would falsify the record.

### 0.7 — Per-user time zone override *(AV-67, E11)*

The organization-level machinery (`services/timezones.py`, `PUT /organization/timezone`,
`TimezoneSetting.tsx`) already existed; only the override is new, exactly as the plan's audit
table predicted.

- `users.time_zone` (nullable `String(64)`); `NULL` means *follow the organization's zone*, so
  the org setting remains the single default.
- Migration `0025_user_time_zone.py` — `batch_alter_table` with the `NAMING` convention
  (`DB-17`). **Chains from `0023`; see the rebase caveat in §2.**
- `GET /me/timezone` and `PUT /me/timezone`, gated `CurrentUser` — deliberately **not**
  tutor-gated, because a student's own zone is theirs to set (the test asserting a student can
  set their own but not the organization's is what pins that distinction).
- Frontend: `MyTimezoneSetting.tsx` mounted on the settings page;
  `supportedTimezones`/`detectedTimezone` exported from the existing `TimezoneSetting.tsx`
  rather than duplicated; `User` gains `time_zone`.
- Four tests in `test_timezones.py`: self set/clear round-trip, student-can-set-own-but-not-org,
  unknown zone → 422, unauthenticated → 401.

### 0.8 — Type safety *(AV-79)*

Two halves, both now gated.

**Backend — mypy.** `mypy>=1.10` in dev deps; `[tool.mypy]` scoped to
`packages = ["app.services", "app.schemas"]` — the service boundaries first, per the plan.
Starting state was **101 errors in 17 files**; ending state is zero, and `.github/workflows/ci.yml`'s
lint job runs the same command so it cannot regress silently. The errors fell into five
patterns, each fixed the same way everywhere:

- `session.get()` results assumed non-null → `assert x is not None` guards at the fetch site
  (loud failure on inconsistent data instead of an `AttributeError` deep in a handler).
- Nullable MIME columns flowing into `tuple[bytes, str]` fields → conditions now require the
  MIME too, so a path-without-mime row degrades to "no file" rather than a type lie.
- `dict(Row-tuples)` mypy cannot infer → annotated dict comprehensions (`groups.py`, `today.py`).
- The Anthropic SDK's strict parameter unions vs. plain-dict wire shapes → targeted
  `# type: ignore[arg-type]`/`[typeddict-item]` at the four SDK call boundaries only, each
  inline; nowhere else.
- Genuine logic gaps worth having found: `raw_marks` could be `None` in the past-paper pct
  computation, and `_aware(existing.generated_at)` could be `None` in two narrative comparisons
  — both now guarded.

Also: `AiResponse.parsed` became `Any` (it genuinely is — provider-validated dynamic data) and
`structured_complete(output_format=...)` tightened from `type` to `type[BaseModel]`.

**Frontend — generated contract.** The backend OpenAPI document is committed at
`frontend/openapi.json`; `npx openapi-typescript` generates `src/api/schema.d.ts` (8.4k lines);
`client.ts` now exports `TokenPair`/`User`/`AuthResponse` and `auth.ts` exports `Organization`
**derived from `components["schemas"]`** instead of hand-mirrored interfaces. For these types,
`FE-4`'s "nothing checks the two agree" is closed by construction. New scripts:
`npm run generate:api`. Regenerate after any response-schema change; the file's header forbids
hand edits.

**Honest note on commit hygiene:** the `0.7` commit was made with `git add -u` and missed its
own untracked new files (`0025`, `MyTimezoneSetting.tsx`); they rode along in `0.8`'s commit,
whose message records this. Content is identical; only the commit boundary is blurred.

### 0.9 — Token-revocation tripwire *(threat review F8)*

The behaviour was already correct (`deps.py:29` for access, `api/auth.py:152` for refresh); the
missing piece was anything that notices if it stops being so. Two additions:

- A `CODE-12` comment at the version check in `deps.py` stating the invariant where a future
  password-reset or account-disable author will read it: bumping `token_version` must kill
  every outstanding token, and any endpoint that invalidates a credential must bump.
- `test_bumping_token_version_invalidates_both_tokens` mutates the row **directly in the DB**,
  deliberately bypassing logout/reset handlers, then asserts: old access → 401, old refresh →
  401, fresh login at the new version → 200. Bypassing the handlers is the point — it tests the
  invariant even if a future handler forgets to do its part.

### 0.10 — AI price table *(AV-2)*

`AI_MODEL_PRICING` is now filled in both places that carry configuration, keyed to the model IDs
`config.py` actually resolves today:

| Model id | input_per_1m | output_per_1m |
|---|---|---|
| `claude-opus-4-8` | $5 | $25 |
| `claude-haiku-4-5` | $3 | $15 |
| `gemini-2.5-pro` | $1.25 | $10 |

The rates are the owner-supplied pair ($5/$25 top tier, $3/$15 mid tier) applied to the current
default model IDs. **These keys have a shelf life:** when task `3.2` executes `AV-124`, the plan
requires repricing for `claude-opus-5`/`claude-sonnet-5`, and the `gemini-2.5-pro` entry becomes
dead weight to drop in the same PR.

Three tripwire tests in `test_ai_pricing.py`: every key in `.env.example` must match a model ID
`get_settings()` can produce (with the two provider defaults required to be priced);
`render.yaml`'s value must equal `.env.example`'s; and `estimate_cost_usd` must price a listed
model exactly and return `None` — never a guess — for an unlisted one (`AI-17`).

---

## 4. Decisions made during this stretch

| Question | Answer |
|---|---|
| Branch topology | Stacked linearly off the docs branch, unlike `0.1`–`0.5`'s parallel cuts — merge order then equals review order. |
| mypy scope | Service boundaries only (`app.services`, `app.schemas`), strictness modest, broadening later. Routers/models/API stay unchecked for now — that is the plan's own "gradual" intent. |
| Type-ignore policy | Only at the four Anthropic SDK call sites, each with a reason. Zero ignores elsewhere; nullability was fixed with real guards. |
| Is Gemini retired in these tasks? | **No — and deliberately.** The owner confirmed "gemini is retired", matching `AV-124`, but the plan assigns the retirement to **task `3.2` as one PR** ("a half-migrated `config.py` is worse than the Gemini routing it replaces"). Until then `config.py` still routes marking/extraction/syllabus to Gemini and `test_ai_provider.py` asserts that correct interim state. `0.10` prices `gemini-2.5-pro` so interim calls are costed; `3.2` drops the entry. |
| Deployment identifiers | Untouched, per standing rule — owner renames repo/hostname/branch manually. |
| graphify plugin droppings (`.gitattributes`, `graphify-out/`) | Never staged, never committed; the stash taken at the start was dropped once confirmed foreign. |

Standing instructions unchanged: no architecture or product guesses; **never merge, only ask
for a PR**; use ECC agents generously; never act on `agentic-os`.

---

## 5. What was verified, and what was not

**Verified, on the stack tip `b20a369` and at every intermediate head:**

- Backend `pytest`: **506 passed** (498 → +4 timezone, +1 revocation, +3 pricing). No assertion
  deleted anywhere.
- Frontend `vitest`: **161 passed**; `npm run build` (`tsc -b && vite build`) clean — bundle
  429 kB / gzip 117 kB.
- `ruff check` + `ruff format --check` clean; `eslint --max-warnings 0` clean.
- **`mypy app/services app/schemas`: 0 errors in 54 files** — and now enforced in CI's lint job.

**Not verified, and why:**

- **Migrations against Postgres.** As with `0024`, `0025` is proven only on SQLite locally;
  CI's Alembic up → down → up job gives the real answer once PRs exist. Watch it on `0.7`
  especially, since `0025` will need rebasing if `0.3` merges first (§2).
- **The generated schema against a running server.** `openapi.json` was exported from
  `app.openapi()` directly — same source FastAPI serves — but nobody has diffed it against a
  booted instance. Low risk; noting for completeness.
- **CI has never run on any of this.** No PRs opened yet at time of writing.

---

## 6. Traps hit along the way

- **A slow machine looks like a hang.** The full backend suite twice exceeded a 10-minute
  foreground timeout while a background rebuild saturated the CPU, yet completed in 3½ minutes
  when re-run detached. Before diagnosing a "hung" pytest here, check load and re-run in the
  background with a polled log file.
- **`git add -u` skips untracked files.** It staged modifications only, so brand-new files from
  the just-finished task silently slipped into the *next* task's commit. Stage explicitly, or
  verify with `git status` before committing.
- **npm's cache directory was root-owned** (`EACCES` on install). Worked around with
  `npm install --cache /tmp/npm-cache`; the permanent fix (`sudo chown -R 501:20 ~/.npm`)
  needs the owner's password and was left to them.
- **mypy on SQLAlchemy 2.0 is mostly one repeated lesson:** relationship/column attributes are
  Optional and comparisons are opaque. The fix set in `0.8` is the pattern library for the next
  widening of scope — reuse it rather than improvising.

---

## 7. Where the plan stands, and what is next

**Phase 0 — Truth and hygiene: complete.** All eleven tasks (`0.0`–`0.10`) are built and
committed across eleven branches (plus two docs-only). Nothing is merged, pushed or deployed;
the owner holds the entire batch.

**Immediately: push and open PRs in stack order** — `0.6` → `0.7` → `0.8` → `0.9` → `0.10`,
plus the two docs branches. Then watch CI, especially the Alembic job (`0024` and `0025` have
never touched Postgres).

**After Phase 0 merges: Phase D — the design pass** *(AV-102/103/104)*, which the plan marks
PARTIAL (identity docs and token set exist; five of ten tutor tabs exist as pages). Per the
owner's instruction, work **stops at the Phase D boundary until they say otherwise**.

**`AV-124` (Gemini retirement) stays parked at task `3.2`**, one PR, with the exact edit list
already written in the plan: bump `anthropic_model` to `claude-opus-5`, flip marking/extraction
providers to `"anthropic"`, give reports/class_brief/narrative explicit `"claude-sonnet-5"`
models, leave `gemini_api_key`/`gemini_model` in place unused, and reprice `AI_MODEL_PRICING`.
Nothing in `0.6`–`0.10` contradicts it; `0.10`'s gemini pricing entry is interim by design.

**Known drift this work created or inherited,** for whoever writes the next handoff: the
constitution's counts (routers/services/handlers) predate `0.3`–`0.5` and are unchanged here;
`docs/README.md`'s pointer to the architecture spec follows the `0.6` rename correctly, but the
historical documents intentionally still say MANARA; and the `0.5` handoff's §8 drift list
remains accurate except where the rename touched naming only.
