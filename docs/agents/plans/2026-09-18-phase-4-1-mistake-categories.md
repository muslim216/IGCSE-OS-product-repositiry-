# Phase 4.1 — Tutor-owned mistake categories — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the fixed five-member `MistakeCategory` enum into a per-(organization, subject) table the tutor owns, edits and archives, with a published starting list that is offered on read and written only on save.

**Architecture:** A direct copy of the grade-boundaries pattern, which solved the same problem — a tutor-owned per-subject list with published defaults that must never be silently persisted. One difference, deliberate: grade boundaries save by delete-then-insert, which cannot work here, because a category a mistake points at must be archived rather than deleted. The PUT therefore diffs.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, pytest; React 18, TypeScript, TanStack Query, Tailwind v4.

**Spec:** `docs/agents/phase-4-spec.md` — section "PR 4.1", plus the settled-decisions table. Read both before Task 1.

## Global Constraints

- **Nothing may branch on a category's value.** No `if name == "careless"`, ever, anywhere. The list is the tutor's, so its contents are data.
- Every new top-level aggregate carries `organization_id` (`PROD-3`, `DB-2`).
- Every query returning tenant data filters by organization derived from the **authenticated user**, never a path or body parameter (`PROD-4`, `SEC-7`).
- Student-visible material is scoped by (organization, subject) (`SEC-8`).
- Return **404, not 403**, for anything the caller may not know exists (`API-7`, `SEC-9`).
- Role gates go in the **signature** — `user: TutorUser` — never in the handler body (`BE-17`, `SEC-11`).
- `api/ -> services/ -> models/`; a lower layer never imports a higher one (`BE-1`).
- Every model re-exported from `models/__init__.py` — a missing one silently gets **no table in tests** (`BE-3`).
- Migrations: hand-written, sequential, chained, working `downgrade()`, `batch_alter_table(..., naming_convention=NAMING)` (`DB-15`, `DB-16`, `DB-17`).
- **Reflect constraint names, never assume them** (`RISK-3`).
- A change touching auth ships with a test asserting the **negative** case (`QA-12`).
- Backend schema change -> regenerate `openapi.json` and `schema.d.ts` in the **same PR** (`FE-4`, `API-15`).
- Semantic token classes only — `bg-surface`, `text-ink-700`, `border-line`; never `bg-white` (`UX-2`).
- `docs/**` and `CLAUDE.md` are updated but **never committed**.
- Docker is unavailable. `DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head` and **check the exit code**.

## File Structure

- `backend/app/models/readiness_v2.py` — **modify**. The `MistakeCategory` *enum* is deleted and the name reused for the new table class. `Mistake.category` becomes `Mistake.category_id`.
- `backend/app/models/__init__.py` — **modify**. Re-export the new model (`BE-3`).
- `backend/alembic/versions/0051_mistake_categories.py` — **create**.
- `backend/app/services/mistake_categories.py` — **create**. Mirrors `services/grade_boundaries.py`.
- `backend/app/schemas/mistake_categories.py` — **create**. Mirrors `schemas/grade_boundaries.py`.
- `backend/app/api/mistake_categories.py` — **create**. Mirrors `api/grade_boundaries.py` almost line for line.
- `backend/app/main.py` — **modify**. Mount the router under `/api/v1`.
- `backend/app/services/readiness_v2.py` — **modify**. `MistakePoint(category=...)` reads a row's name, not an enum's `.value`.
- `backend/tests/test_mistake_categories.py` — **create**.
- `backend/tests/test_readiness_v2.py`, `backend/tests/test_past_papers.py` — **modify**. Both construct `Mistake(category=MistakeCategory.careless, ...)` and must move to a category row.
- `frontend/src/tutor/MistakeCategoriesPage.tsx` — **create**, copying `GradeBoundariesPage.tsx`.
- `frontend/src/api/mistakeCategories.ts` — **create**.
- `frontend/src/App.tsx` — **modify**. Route beside grade boundaries.
- `frontend/openapi.json`, `frontend/src/api/schema.d.ts` — **regenerate**.

---

### Task 1: The model and the migration

**Files:**
- Modify: `backend/app/models/readiness_v2.py:42-66`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0051_mistake_categories.py`

**Interfaces:**
- Produces: `MistakeCategory` (table model: `id`, `organization_id`, `subject_id`, `name`, `description`, `archived_at`) and `Mistake.category_id: Mapped[int]`.

- [ ] **Step 1: Read the two reference files before writing anything**

```bash
cd backend
sed -n '215,240p' app/models/readiness_v2.py
sed -n '1,45p' alembic/versions/0050_submission_mistakes_analysed_at.py
```

`GradeBoundary` is the scoping precedent; `0050` carries the `NAMING` dict and revision style. Copy both **verbatim**. Do not retype either from memory.

- [ ] **Step 2: Replace the enum with the table**

Delete the `MistakeCategory` enum class at `backend/app/models/readiness_v2.py:42-47` and put the table in its place:

```python
class MistakeCategory(TimestampMixin, Base):
    """A kind of mistake, named by the tutor who teaches the subject.

    This was a five-member enum. It is a table because the words a tutor uses
    for what went wrong are theirs: "careless" is not a category every subject
    or every teacher recognises, and a fixed list quietly tells a tutor their
    vocabulary is wrong.

    **Nothing may branch on a category's value.** No `if name == "careless"`.
    The contents are tutor data, so code that reads meaning into them breaks
    the moment someone renames one — silently, because a rename is a valid
    edit and nothing would fail.

    Scoped per (organization, subject) like GradeBoundary, for the same reason:
    a subject is owned by one tenant, but tutors sharing an organization share
    its setup, and no tenant may ever see another's (SEC-8).
    """

    __tablename__ = "mistake_categories"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "subject_id",
            "name",
            name="uq_mistake_categories_organization_id_subject_id_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Written for the model to read, not only the tutor: 4.2 passes this list
    # into the tagging prompt, and a bare word like "careless" is ambiguous to
    # anything that has not sat in the room.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Archived, never deleted — mistakes already tagged with it must keep
    # reading back. An archived category is hidden from new tagging and from
    # the editor's live list, and nothing else about it changes.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Confirm the file's imports already cover `UniqueConstraint`, `String`, `Text`, `DateTime`, `ForeignKey` and `datetime`; add whatever is missing.

- [ ] **Step 3: Point `Mistake` at it**

In the same file, replace `Mistake.category` with:

```python
    category_id: Mapped[int] = mapped_column(ForeignKey("mistake_categories.id"), nullable=False)
```

- [ ] **Step 4: Re-export the model**

Add `MistakeCategory` to `backend/app/models/__init__.py` in both the import block and `__all__`. It was already exported from that module as an enum, so check whether the name is present — if it is, confirm it now resolves to the new class rather than assuming.

`BE-3` is not cosmetic: Alembic's `env.py` and the test schema both build from that barrel, so a model missing from it gets no table in tests and the failure reads as a confusing "no such table".

- [ ] **Step 5: Write migration `0051`**

Create the table and swap the column. **No backfill — nothing in `backend/app` has ever written a `mistakes` row, so the table is empty.**

```python
"""mistake categories become a tutor-owned table

The five-member MistakeCategory enum said every tutor of every subject sorts
mistakes the same way. They do not, and a tutor who disagreed had nothing to
change. The table is scoped per (organization, subject) like grade_boundaries,
and a category in use is archived rather than deleted so already-tagged
mistakes keep reading back.

No data migration: nothing in backend/app has ever written a `mistakes` row,
so there is no enum value to translate. `downgrade()` therefore refuses rather
than guessing which enum member a tutor's own category was.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-18

"""
```

`upgrade()` — `op.create_table("mistake_categories", ...)` with the unique constraint **named explicitly**, then `batch_alter_table("mistakes", naming_convention=NAMING)` to drop `category` and add `category_id` as a **named** ForeignKey. `DB-17`: SQLite rebuilds tables on ALTER and refuses unnamed reflected constraints.

`downgrade()` — recreate the `category` enum column, drop `category_id`, drop the table. Follow `0049`'s shape: count `mistakes` rows first and `raise RuntimeError` naming the count if any exist, because a tutor's own category has no enum member to become.

- [ ] **Step 6: Verify the migration up, down, and up**

```bash
cd backend
rm -f /tmp/x.db
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head; echo "up: $?"
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic downgrade 0050; echo "down: $?"
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head; echo "up: $?"
```

All three must print `0`. **Read the exit codes** — plausible output above a non-zero code is the `RISK-3` failure exactly.

- [ ] **Step 7: Fix the three places that used the enum**

`tests/test_readiness_v2.py` and `tests/test_past_papers.py` both construct `Mistake(category=MistakeCategory.careless, ...)`; each needs a `MistakeCategory` **row** first and `category_id=` instead.

`services/readiness_v2.py` builds `MistakePoint(category=m.category.value, ...)` and now needs the row's `name`. Join or `selectinload` it — do **not** add a lazy relationship access inside the loop, which is a blocking call per row (`BE-13`, `PERF-1`).

- [ ] **Step 8: Full suite, linters, type check**

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/python -m mypy app/services app/schemas
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/alembic backend/app/services/readiness_v2.py backend/tests
git commit -m "Mistake categories are the tutor's words, not the enum's"
```

---

### Task 2: The service — defaults offered, never written

**Files:**
- Create: `backend/app/services/mistake_categories.py`
- Test: `backend/tests/test_mistake_categories.py`

**Interfaces:**
- Produces:
  - `DEFAULT_CATEGORIES: list[dict]` — module constant of `{"name": str, "description": str}`
  - `defaults_for_subject() -> list[dict]`
  - `list_categories(session, organization_id, subject_id) -> list[MistakeCategory]` — live rows only
  - `save_categories(session, organization_id, subject_id, items) -> list[MistakeCategory]` — diffs
  - `ensure_categories(session, organization_id, subject_id) -> list[MistakeCategory]` — get-or-write defaults
- Callers: Task 3 (the API) and PR 4.2 (the tagging job).

- [ ] **Step 1: Read the module this one copies**

Run: `sed -n '1,70p' backend/app/services/grade_boundaries.py`

Match its docstring discipline. The line that matters is "**Defaults are offered, never written**" — that is the whole design, and it is why 4.1 needs no data migration.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_mistake_categories.py`:

```python
async def test_defaults_are_offered_not_written(session, org_and_subject):
    org_id, subject_id = org_and_subject
    assert await list_categories(session, org_id, subject_id) == []
    assert defaults_for_subject()

    stored = (await session.scalars(select(MistakeCategory))).all()
    assert stored == []          # reading did not persist


async def test_save_archives_what_the_payload_drops(session, org_and_subject):
    """A category a mistake points at cannot be deleted, so an edit that
    removes it archives it. This is the one place 4.1 diverges from the
    grade-boundary precedent, which replaces by delete-then-insert."""
    org_id, subject_id = org_and_subject
    saved = await save_categories(
        session, org_id, subject_id, [{"name": "careless"}, {"name": "content gap"}]
    )
    keep = next(c for c in saved if c.name == "careless")

    await save_categories(session, org_id, subject_id, [{"id": keep.id, "name": "careless"}])

    live = await list_categories(session, org_id, subject_id)
    assert [c.name for c in live] == ["careless"]
    gone = await session.scalar(
        select(MistakeCategory).where(MistakeCategory.name == "content gap")
    )
    assert gone is not None and gone.archived_at is not None


async def test_ensure_categories_writes_the_defaults_once(session, org_and_subject):
    """4.2's tagging job needs rows to point an FK at, and decision 3 says
    nothing is seeded at subject setup — so the first tagging run is what makes
    the defaults real. Twice must not double them."""
    org_id, subject_id = org_and_subject
    first = await ensure_categories(session, org_id, subject_id)
    second = await ensure_categories(session, org_id, subject_id)
    assert [c.id for c in first] == [c.id for c in second]
    assert len(first) == len(DEFAULT_CATEGORIES)


async def test_a_rename_keeps_the_row_so_old_mistakes_follow_it(session, org_and_subject):
    org_id, subject_id = org_and_subject
    saved = await save_categories(session, org_id, subject_id, [{"name": "careless"}])
    original_id = saved[0].id

    renamed = await save_categories(
        session, org_id, subject_id, [{"id": original_id, "name": "slip"}]
    )
    assert renamed[0].id == original_id
    assert renamed[0].name == "slip"


async def test_an_id_from_another_organization_is_not_found(session, org_and_subject, other_org):
    """A foreign id in the payload is not found — never someone else's row
    updated because the id happened to exist (SEC-7)."""
    ...
```

Build the `org_and_subject` fixture from `tests/factories.py` — `org_id` and `make_subject` are already there, and `other_org_subject` is at `tests/factories.py:66`.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mistake_categories.py -v`
Expected: FAIL with `ModuleNotFoundError` — the service does not exist yet.

- [ ] **Step 4: Write the service**

Module docstring:

```python
"""Where a subject's mistake categories come from — one source, and this module.

**Defaults are offered, never written.** `DEFAULT_CATEGORIES` is what the
editor pre-fills and what `ensure_categories` writes on first use; until one of
those happens this organization has no categories and the table says so. The
same discipline as `services/grade_boundaries.py`, for the same reason: a
published starting point written on a tutor's behalf is indistinguishable from
their own decision afterwards.

**Saving diffs; it does not replace.** Grade boundaries replace by
delete-then-insert, which cannot work here — a category a Mistake row points at
must survive being dropped from the editor, or the mistake loses the word it
was tagged with. Dropped categories are archived: hidden from new tagging and
from the editor, still readable on everything already tagged.

**Nothing here or anywhere else may branch on a category's name.** The contents
are tutor data. Code that reads meaning into them breaks on a rename, and a
rename is a valid edit that fails nothing.
"""
```

`DEFAULT_CATEGORIES` — the five existing enum members (decision 6), each with a description written for 4.2's prompt to read:

```python
DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "Misread the question",
        "description": "Answered something the question did not ask — a misread instruction, a missed condition, the wrong quantity.",
    },
    {
        "name": "Content gap",
        "description": "The underlying method or fact was not known, not merely mis-executed.",
    },
    {
        "name": "Careless",
        "description": "The method was right and known; execution slipped — a dropped sign, a copied digit, a skipped line.",
    },
    {
        "name": "Calculation",
        "description": "The approach was correct but the arithmetic or algebra went wrong.",
    },
    {
        "name": "Time management",
        "description": "Left blank, abandoned part-way, or visibly rushed at the end of the paper.",
    },
]
```

`save_categories` diffs:
- an item **with** an `id` updates that row's name and description, after checking the row belongs to this (organization, subject) — a foreign id is **not found**, never someone else's row (`SEC-7`)
- an item **without** an `id` is created
- a live row whose id is absent from the payload gets `archived_at` set
- a save reintroducing an archived name **un-archives that row** rather than inserting a duplicate the unique constraint would reject

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mistake_categories.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/mistake_categories.py backend/tests/test_mistake_categories.py
git commit -m "A subject's mistake categories, offered before they are written"
```

---

### Task 3: The endpoints

**Files:**
- Create: `backend/app/schemas/mistake_categories.py`
- Create: `backend/app/api/mistake_categories.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_mistake_categories.py`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: `GET`/`PUT /api/v1/subjects/{subject_id}/mistake-categories`, response model `MistakeCategoriesOut` carrying `subject_id`, `subject_name`, `source` (`"organization"` | `"none"`) and `categories`.

- [ ] **Step 1: Read the router this one copies, in full**

Run: `cat backend/app/api/grade_boundaries.py`

94 lines, and 4.1's router is the same shape: `GET` uses `visible_subject` and `CurrentUser`, `PUT` uses `owned_subject` and `user: TutorUser`, and `source` travels with the payload so the UI can tell the tutor's own list from a starting point nobody confirmed (`PROD-8`). Both helpers are in `app/api/deps.py`.

- [ ] **Step 2: Write the failing negative-case tests first (`QA-12`)**

```python
async def test_a_student_cannot_write_categories(client, student, subject):
    r = await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "careless"}]},
        headers=student["headers"],
    )
    assert r.status_code in (401, 403)


async def test_another_organizations_subject_is_404_not_403(client, tutor, other_org_subject):
    """404, not 403: integer keys are enumerable, and 403 confirms the row
    exists to someone who may not know it does (API-7, SEC-9)."""
    r = await client.get(
        f"/api/v1/subjects/{other_org_subject.id}/mistake-categories",
        headers=tutor["headers"],
    )
    assert r.status_code == 404


async def test_get_offers_defaults_and_says_they_are_not_set(client, tutor, subject):
    r = await client.get(
        f"/api/v1/subjects/{subject['id']}/mistake-categories", headers=tutor["headers"]
    )
    assert r.status_code == 200
    assert r.json()["source"] == "none"
    assert len(r.json()["categories"]) == 5


async def test_put_then_get_reports_the_organizations_own(client, tutor, subject):
    await client.put(
        f"/api/v1/subjects/{subject['id']}/mistake-categories",
        json={"categories": [{"name": "careless", "description": "slip"}]},
        headers=tutor["headers"],
    )
    r = await client.get(
        f"/api/v1/subjects/{subject['id']}/mistake-categories", headers=tutor["headers"]
    )
    assert r.json()["source"] == "organization"
    assert [c["name"] for c in r.json()["categories"]] == ["careless"]
```

- [ ] **Step 3: Run to verify they fail**

Expected: FAIL with 404 on the route itself — it is not mounted yet.

- [ ] **Step 4: Write the schemas, the router, and mount it**

Schemas mirror `schemas/grade_boundaries.py`. `MistakeCategoryIn` carries optional `id`, required `name` (1-60 chars, stripped, non-empty) and optional `description`. **Reject duplicate names within one payload in the schema**, so the unique constraint never raises a 500 at the tutor.

Router mirrors `api/grade_boundaries.py`. Mount in `main.py` beside the grade-boundaries router.

- [ ] **Step 5: Run the file, then the full suite**

```bash
cd backend && .venv/bin/python -m pytest tests/test_mistake_categories.py -v && .venv/bin/python -m pytest -q
```

- [ ] **Step 6: Regenerate the API contract (`FE-4`, `API-15`)**

```bash
cd backend && python -c "import json;from app.main import app;print(json.dumps(app.openapi(),indent=2))" > ../frontend/openapi.json
cd ../frontend && npm run generate:api
```

Both commands assume those working directories. CI fails on a diff in either, so this is not optional.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api backend/app/schemas backend/app/main.py backend/tests frontend/openapi.json frontend/src/api/schema.d.ts
git commit -m "A tutor reads and sets their own mistake categories"
```

---

### Task 4: The tutor screen

**Files:**
- Create: `frontend/src/tutor/MistakeCategoriesPage.tsx`
- Create: `frontend/src/api/mistakeCategories.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Read the page this one copies**

Run: `sed -n '1,200p' frontend/src/tutor/GradeBoundariesPage.tsx`

Lines 135-187 are the pattern: a tutor-editable list held in local draft state, add/edit/remove, saved in one mutation, with inline validation that disables save. Copy the structure; the editing unit is a `{name, description}` row rather than a `{grade, min}` band.

- [ ] **Step 2: Write the API wrapper**

`frontend/src/api/mistakeCategories.ts` goes through `api/client.ts` — the one HTTP entry point (`FE-1`). Types alias `components["schemas"][...]` from the generated `schema.d.ts`; **do not hand-write an interface** (`FE-4`).

- [ ] **Step 3: Write the page**

Server data lives in TanStack Query, not copied into `useState` (`FE-6`). The draft list being edited is local state, which is a different thing and correct. Semantic token classes only (`UX-2`).

When `source === "none"`, label the list as a starting point nobody has confirmed (`PROD-8`, `UX-20`). Do not render it as though the tutor chose it.

- [ ] **Step 4: Route it**

Add the route in `frontend/src/App.tsx` beside the grade-boundaries one, behind the same tutor gate. A frontend role gate is never an authorization control (`SEC-10`) — the real gate is `TutorUser` in Task 3's signature.

- [ ] **Step 5: Verify**

```bash
cd frontend && npm test && npm run lint && npm run build
```

`npm run build` is `tsc -b && vite build`, the only type check anywhere, so it must run.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "A tutor edits their mistake categories beside their grade boundaries"
```

---

### Task 5: Documentation, review, PR

- [ ] **Step 1: Update the constitution (`GOV-1`, `CODE-21`)**

- `docs/governance/glossary.md` — add *mistake category* and *archived category*.
- `docs/volume-2-application-engineering/06-database-design.md` — the new table.
- `docs/avora-new-state-august-16.md` — mark 4.1 done, and note that "seeded at subject setup" was replaced by defaults-on-read, with the reason (it removes the data migration entirely).

All left **uncommitted**.

- [ ] **Step 2: Write the ADR**

The enum -> tutor-owned table decision is hard to reverse, surprising without context, and the result of a real trade-off — a fixed vocabulary is simpler, and was rejected because it tells a tutor their words are wrong. That is all three tests, so it earns an ADR in `docs/adr/`.

- [ ] **Step 3: Run the review set — the full four, plus one**

Migration, new endpoints and a new model, so: `ecc:database-reviewer`, `ecc:fastapi-reviewer`, `ecc:security-reviewer`, `ecc:python-reviewer`, and `ecc:react-reviewer` for Task 4.

**Give every reviewer this question explicitly**, because it is what review caught twice in 4.0 and the plan did not: *which existing readers and writers of `mistakes`, `submissions` or `subjects` does this change make wrong without changing them?*

- [ ] **Step 4: Open the PR, staging code by path**

```bash
git add backend/app backend/tests backend/alembic frontend/src frontend/openapi.json
git status   # confirm nothing under docs/ or CLAUDE.md is staged
```

- [ ] **Step 5: Read the bots' inline comments**

```bash
gh api repos/:owner/:repo/pulls/N/comments
curl -s "https://sonarcloud.io/api/issues/search?componentKeys=muslim216_IGCSE-OS-product-repositiry-&pullRequest=N&resolved=false"
```

A green `gh pr checks` is not evidence. Fix, push, re-read, then merge.
