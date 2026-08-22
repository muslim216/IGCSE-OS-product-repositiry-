# 05 — Data and Storage

*What gets stored, how it's organised, and the design rules behind it.*

The data is the company's actual asset. The code could be rewritten in a few months; the accumulated academic record of hundreds of students could not be recreated at all.

---

## The shape of it

52 tables, grouped into areas that map cleanly onto the product:

| Area | Holds |
|---|---|
| **People & access** | Users, organisations, invites, parent links |
| **Teaching structure** | Groups, subjects, topics, timetable slots, lessons |
| **The student record** | Profiles, subject enrolments, tutor notes, parent communications |
| **Homework** | Booklets, questions, submissions, files, marks, override log, appeals |
| **Past papers** | Papers, questions, student attempts |
| **Readiness** | Evidence, topic scores, factor calculations, snapshots, weights, grade boundaries, mistakes |
| **AI** | Usage events, chat conversations and messages, knowledge base entries |
| **Operations** | The job queue, reports, uploaded syllabuses, Google Classroom links |

---

## How customers are kept separate

Every tutor gets their own **organisation**, created automatically when they sign up. Students and parents inherit the organisation of the tutor who created them.

Every significant record carries a stamp saying which organisation it belongs to, and every query is supposed to filter by it.

### The bet worth understanding

The database has supported **multiple tutors sharing one organisation from day one**, even though the product deliberately only ever shows a single-tutor experience.

That looks like over-engineering. It isn't, and the reasoning is worth borrowing:

> The database decision is expensive to reverse, so it was made early. The interface decision is cheap to reverse, so it was deferred.

The day a tutoring centre with six tutors wants to buy, supporting them should be an interface change and a new role — a few weeks. Without this decision it would be a database migration on live customer data, which is months of work and the single most dangerous kind of change you can make.

The internal standard is strict about maintaining it: any new table must carry the organisation stamp. A table without it turns "go multi-tutor later" back into the expensive migration this decision exists to avoid.

**The gap:** a proper safety mechanism to enforce this filtering exists in the code — and is used nowhere. Every query filters manually instead. It's correct today, but the separation between one tutor's data and another's depends on every developer remembering one line, every time, with nothing catching a mistake. That's weakness #9 in the [weaknesses document](../Product-Overview-and-Weaknesses.md).

### One deliberate exception

**Subjects and their topic trees are global** — every organisation shares the five built-in syllabuses. That's correct; there's no reason for every tutor to have their own copy of the Edexcel Maths topic tree.

But it has a sharp edge that has caused real bugs. Because subjects are shared, anything matched on subject *alone* would show a student every past paper every tutor anywhere had uploaded. So past-paper visibility is scoped by organisation **and** subject together, derived from the groups a student is actually in.

That last detail is subtle and correct: a student who joined a second tutor's class by invite sees that tutor's papers, and only that tutor's. Scoping by the student's own organisation would have got this wrong.

---

## Records that can never be changed

Most tables hold current values — a student's readiness score is *the* score, updated in place.

But where history matters, Avora keeps **append-only** records: rows are added and never edited or deleted.

| Table | Why it can never be edited |
|---|---|
| **Evidence** | The permanent record of what a student did |
| **Factor evaluations** | One row per factor per calculation — the audit trail behind every score |
| **Readiness history** | How readiness changed over time |
| **Mark override log** | Every change a tutor made to a mark — old value, new value, who, when |

The override log is the sharpest example. **There is no way for anyone to edit or delete those rows** — no button, no admin screen, no API. Not because it was forgotten, but because an audit trail that can be edited isn't an audit trail.

This is what makes the product's central promise real. When a parent asks why their child's readiness dropped, the answer is a queryable list of records, not a recollection.

---

## Six deliberate design decisions

Each of these was written down as a decision with a stated cost, which is unusual and worth noting on its own.

### Simple sequential IDs, not random ones

Every record is numbered 1, 2, 3. Chosen for consistency across 52 tables, smaller and faster indexes, and readability in support conversations.

**The stated cost:** IDs are guessable. Someone can trivially try record #47 instead of #46. So security can *never* rely on IDs being hard to guess — every request must verify the user is actually allowed to see that specific record. The system does this. The point is that the cost was named and paid explicitly rather than discovered later.

### Deletion means deletion

There's no "marked as deleted but still there" anywhere. When something is deleted, it's gone.

**Why:** soft deletion leaks into every query in the system, and every query that forgets to exclude deleted rows becomes a data-leak bug. Where history genuinely matters, an append-only table is used instead.

### Background jobs live in the database

No separate queuing service, no Redis, no message broker. A background job is a row in a table.

**Why:** one datastore is one thing to back up, one thing to restore, one thing to reason about, and one place a job can hide. A job is a row you can look at with an ordinary query.

This is the clearest example of the project's overall philosophy: every extra dependency is a permanent tax paid by everyone who touches the system afterwards.

### Database changes are hand-written

Schema changes are written by hand, numbered in order, and reviewed like code — rather than auto-generated by a tool.

**Why:** auto-generated changes produce diffs nobody reads and miss data migrations entirely. There are 21 of these to date, and they run automatically when a new version is deployed.

**The sharp edge:** because they run at startup, a broken schema change means the service doesn't start at all — it takes the whole system down rather than degrading gracefully. This happened once. There's now an automated check that runs every change forwards and backwards against a real database before it can be merged, though that check runs against an *empty* database, and the one failure that actually occurred was a change that worked on empty tables and failed on real data.

### One application, not many small ones

Everything is one backend and one frontend. No microservices.

**Why:** the whole system is ~12,400 lines serving a single-tutor product. Splitting it would add network failures, distributed transactions and deployment coordination to buy independent scaling nobody needs.

The stated trigger for revisiting: if one part genuinely needs different hardware — document processing needing far more memory, say. Then extract that one thing. Don't split on principle.

### One database, one region

No replicas, no multi-region. Revisited when users are geographically spread enough that distance is the bottleneck.

---

## Files are stored differently, and this is the weak point

Uploaded PDFs, mark schemes and photographs of student work are **not** in the database. They're files on a disk, and the database stores only each file's address.

That's a normal and sensible design — databases are bad at holding large files.

The problem is where the disk is: **a single 10 GB disk attached to one server, with no backup, no restore procedure, and no check that files still match their records.**

The consequences, stated plainly:

- If that disk is lost, every piece of student work ever submitted is gone — and the database keeps confidently pointing at files that no longer exist.
- Nothing monitors how full it is. It can simply fill up one day and start rejecting uploads.
- Because the disk is attached to one specific server, the system **cannot run on more than one server** — which is one of three separate things capping growth.

The code was deliberately written to make moving to proper cloud storage easy: only relative addresses are stored, so the move is a swap rather than a rewrite. It just hasn't been done.

For a product whose entire promise is "we keep a complete academic record," losing the record isn't a technical incident. It's weakness #1 in the [weaknesses document](../Product-Overview-and-Weaknesses.md), and it's the thing to fix first.

---

## What's stored about children

Worth stating explicitly, because it determines what's needed before selling to anyone larger than an individual tutor:

- Named children, with their school and year group
- Their complete academic history — every mark, every piece of evidence
- **Photographs of their handwriting**
- Parent names and contact details
- Records of communications with parents
- Chat conversations between students and the AI mentor

The engineering protections around this data are genuinely good: login credentials handled properly, sessions revocable instantly, uploads validated by inspecting actual file contents rather than trusting the file name, parent invite links that work exactly once.

What doesn't exist is everything around them: no data classification, no retention policy, no deletion path, no data-processing agreement, no stated legal basis for holding any of it.

This is founder work rather than engineering work, and it's on the critical path to any school or tutoring-centre deal — the first due-diligence questionnaire will ask, and the first "please delete my child's data" request will find there's no mechanism to do it. Weakness #2.

---

## What all this adds up to

The data model is the most carefully built part of Avora, and it's the part that would be hardest for a competitor to replicate. The traceability, the append-only audit trails, the multi-tenant foundation laid before it was needed — these are decisions that pay off over years and are painful to retrofit.

The gap is between how well the data is *modelled* and how well it's *protected*. The design is thoughtful, documented, and defensible. The backups, the retention policy and the deletion path aren't there yet.

Those are days of work, not months. They're just days of work nobody has done.
