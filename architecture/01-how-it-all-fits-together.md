# 01 — How It All Fits Together

*The map. Everything else assumes you've read this.*

---

## The system in three pieces

Almost every web product is three things, and Avora is no exception:

**1. The app you see (the "frontend")**
Everything visual — pages, buttons, dashboards, the upload screen. It runs inside the user's web browser. Written in React and TypeScript, about 12,400 lines, roughly 60 screens.

**2. The engine you don't see (the "backend")**
Where the actual work happens: checking passwords, running the readiness calculations, talking to AI providers, deciding who's allowed to see what. Written in Python, about 12,800 lines. Users never see it directly — the app talks to it on their behalf.

**3. The memory (the "database")**
Where everything is permanently kept: users, groups, homework, marks, evidence, scores. A PostgreSQL database with 53 tables.

Plus one thing that sits slightly outside those three:

**4. The file store**
Actual files — uploaded PDFs, mark schemes, photographs of handwritten work. These aren't kept in the database. They sit on a disk, and the database stores only the *address* of each file, like a library catalogue that tells you the shelf but doesn't contain the book. *(This split has a real consequence — see the weaknesses document.)*

## What happens when someone clicks something

Take a concrete example: **a student opens their readiness page.**

1. The student taps "Readiness" in the app.
2. The app sends a request to the engine: *"give me the readiness for whoever this is."*
3. Attached to that request is a **token** — a signed digital pass proving who they are, issued when they logged in.
4. The engine checks the token. Is it valid? Not expired? Not revoked? If any check fails, the request is rejected immediately.
5. The engine works out which student this is, and confirms they're only asking for their own data.
6. It reads the latest readiness scores from the database.
7. It sends back the numbers.
8. The app draws the page.

The whole round trip takes a fraction of a second. The important part is **step 4 and 5**: identity is verified on every single request. The app being open on your phone is not what makes you authorised — the token attached to each request is.

## The one rule that shapes the entire backend

The engine is arranged in three layers, and the rule is that **information flows in one direction only:**

```
   api/          "the front desk"  — receives requests, checks permissions, replies
     ↓
   services/     "the workshop"    — does the actual thinking
     ↓
   models/       "the filing system" — defines what's stored and how
```

The front desk can call the workshop. The workshop can call the filing system. **Nothing ever goes back up.** The filing system knows nothing about the front desk.

Why this matters commercially: the workshop is used by two completely different callers — live requests from users, *and* background work happening on a schedule. Because the thinking lives in the workshop rather than the front desk, both get the same behaviour for free. If the marking logic lived at the front desk, the background pipeline couldn't use it and it would have to be written twice — two copies that drift apart, and a fix applied to one silently doesn't apply to the other.

By the numbers: 27 front-desk modules covering 133 route handlers, 31 workshop modules, 17 filing-system modules covering 53 tables.

## Work that happens in the background

Some things are too slow to make a user wait for. Reading a 40-page PDF and extracting every question takes a minute or more. Marking a submission means sending images to an AI provider. Nobody should stare at a spinner for that.

So Avora has a **job queue.** When something slow needs doing:

1. A row is written to a `jobs` table saying what needs to happen.
2. The user gets an immediate response — *"we're working on it."*
3. A background **worker** picks the job up moments later and does it.
4. When it's finished, the result appears in the app.

There are **ten kinds of background job:**

| Job | What it does |
|---|---|
| `extract_assignment` | Read a homework booklet, pull out the question list |
| `extract_past_paper` | The same, for a full past paper |
| `mark_submission` | Mark a student's submitted work |
| `recompute_readiness` | Recalculate readiness scores (old engine) |
| `compute_readiness_v2` | Recalculate readiness scores (new engine) |
| `generate_report` | Write a progress report |
| `extract_syllabus` | Read a syllabus PDF, draft a topic tree |
| `sync_classroom` | Import work from Google Classroom |
| `generate_narrative` | Write a stored narrative paragraph for one audience |
| `sweep_parent_narratives` | Find which students are due a parent narrative and queue one each |

That last pair is the one piece of genuinely *scheduled* work in the system. The sweep re-enqueues its own successor a configured interval ahead (24 hours by default), committing the next one first so the schedule survives the current run failing. Everything else on this list runs only because a user action queued it.

**Three design details worth knowing, because they're the difference between this working and not:**

**Nothing is lost if the system restarts.** The job is written down *before* it runs. A server restart mid-job means the work is picked up again, not forgotten. If jobs lived only in memory, a routine deployment would silently drop every piece of homework being marked at that moment.

**Retried jobs are designed not to corrupt state, but "safe to run twice" isn't uniform across all ten handlers.** For the ones that write over a fixed target — marking *updates* existing marks rather than adding new ones, and question extraction *replaces* the question list rather than appending to it — a retry can't double a student's marks. For others, "safe" means something looser: `recompute_readiness` and `compute_readiness_v2` append a new run rather than mutating one in place, so a retry adds an extra (consistent) record rather than a duplicate answer; the AI-calling handlers can simply repeat a paid API call on retry. Nothing about a retry corrupts data, but the guarantee is per-handler, not a single blanket property.

**A job never overwrites a human decision.** If a tutor has finalised a mark, re-running the marking job leaves it alone. The tutor's authority isn't a policy statement — it's built into how the pipeline behaves.

If a job fails, it's tried once more after a 60-second wait. If it fails again it's recorded as failed, with the reason stored somewhere the tutor can see it. *(Nothing alerts anyone when this happens — see the weaknesses document.)*

## Where it all runs

Two hosting providers, one job each:

**Vercel** serves the app — the thing users actually open. It's the only address users ever type.

**Render** runs the engine, the database, and the file disk. Users never touch it directly.

The clever bit that makes this work: when the app needs the engine, it doesn't call Render directly. It calls **its own address**, and Vercel quietly forwards the request to Render behind the scenes.

This isn't a technical curiosity — it's a security decision. Because the browser only ever sees one address, the app can use a **cookie** to keep users logged in. A cookie marked `HttpOnly` is the safest place to hold a renewal credential, because code running on the page cannot read it — so a malicious script injected into the page cannot walk off with the session. (It could still *use* the logged-in session while the page is open; what the cookie prevents is the credential being exfiltrated and reused elsewhere later.) That protection only works when everything appears to come from one address. Call Render directly and the browser treats it as a different site, refuses to send the cookie, and users get logged out whenever their session needs renewing.

## How login works

Two credentials, deliberately different:

**The access token** — a short-lived pass, sent with every request. Held in the browser's storage, where page code can read it. That's an accepted trade-off: it expires quickly.

**The refresh token** — used only to get a new access token when the old one expires. Kept in a cookie that page code *cannot* read (`HttpOnly`, `Secure`, `SameSite=Lax`, scoped to the session-renewal address only), and the frontend deliberately never copies it into browser storage of its own.

The result: a script that got into the page can't read the renewal credential out of storage, and can't read it out of the cookie.

**One gap, worth stating rather than glossing:** the login and refresh endpoints currently also return the refresh token in the ordinary JSON response body, which page code *can* read at the moment it arrives. The cookie is therefore not the only copy in transit, and the protection above is weaker than the design intends. This is pre-existing behaviour, not a deliberate design decision, and the fix (return only the access token; let the cookie carry the rest) belongs in its own change to the auth endpoints and their response schema. Note also that `HttpOnly` never prevented an injected script from *making* authenticated requests as the user — it only stops it from walking off with the credential.

**Logging out actually logs you out.** Every user has a version number stamped inside their tokens. Logging out bumps that number, which instantly invalidates every token ever issued to that account — including ones an attacker might be holding. Most systems just delete the token on your device and let stolen copies keep working until they expire.

The same thing happens when a tutor resets a student's password. That's not incidental: resetting a password is how a tutor kicks out whoever else has been sharing an account, so it has to end the sessions that account already has, not just change what a future login requires.

Other limits: failed logins are throttled to 10 per 15 minutes per account, invite codes expire after 14 days, and parent invite links work exactly once.

## The four kinds of user

| Role | Sees | Cannot |
|---|---|---|
| **Student** | Own readiness, own homework and past papers, own exam results, class files, AI chat | See other students; generate reports; download a mark scheme |
| **Tutor** | Everything belonging to their own practice | Reach another tutor's data |
| **Parent** | Plain-language progress for their linked children only | See anything not explicitly linked to them |
| **Admin** | Everything a tutor sees, plus report generation | — |

The permission check happens in a specific and deliberate way. Rather than each page *remembering* to check permissions — which fails silently the day someone forgets — the requirement is declared as part of the request's definition. A request that requires a tutor **cannot be processed at all** without one.

The distinction is between a lock you have to remember to use, and a door that can't open without a key. This codebase used to work the first way, in eleven duplicated copies, and was deliberately rebuilt the second way. There's now an automated test that fails if anyone reintroduces the old pattern.

## The operating loop

Everything in the product exists to move a student around one cycle:

```
   Teach  →  Assign  →  Submit  →  AI marks  →  Readiness updates
     ↑                                                    ↓
     └───────  Plan next lesson  ←  Tutor reviews  ←──────┘
```

This is the actual design principle, not a marketing diagram. Every arrow is a real event stored in the database. A lesson records what was taught. Homework hangs off the lesson that set it. A submission is the student's work. Marks become evidence. Evidence drives readiness. Readiness tells the tutor what to teach next — which starts the loop again.

The internal test for whether a new feature belongs in Avora is whether it sits somewhere on this loop. A feature that fits nowhere on it needs a deliberate decision rather than drifting in.

## The size of the thing

| | |
|---|---|
| Backend | ~12,800 lines of Python in `backend/app` (~16,000 counting blanks and comments) |
| Frontend | ~12,400 lines of TypeScript in `frontend/src` (~13,800 raw), ~60 screens |
| Database | 53 tables, 23 migrations on this branch |
| Requests the app can make | 133 route handlers |
| Background job types | 10 |
| Automated tests | ~9,300 lines in `backend/tests` (~11,500 raw) |

*Counted on this branch, excluding blank and comment lines unless stated. Figures drift with every merge — treat them as scale, not specification.*

This is a real application. Not a prototype, not a demo — a substantial system that a small team could work on for years.
