# The cleanup stage, step by step

**Status:** approved by the owner on 11 October 2026. Nothing in it is built yet.
**Readers:** the owner first, then any AI agent or developer who picks the work up.
**Where it sits:** after Phase 9, before the class reorganisation (B.4), the marking-rules line
(B.1) and Phase 10. The plan's own entry is "The cleanup stage" in
`avora-new-state-august-16.md`; where the two differ, **this document wins**.

Each step below has two parts. **For the owner** is plain words: what the step does, why, and
what you will see when it is done. **For the builder** is the detail an agent or developer needs.
You can read only the first part of every step and still know the whole stage.

---

## 1. Read this first

**What the stage is for.** The owner's words, 11 October: *"by the end of this cleanup stage i
want the infrastructure to be secure and any thing that fell through the cracks while building
the phase 0 to 9 to be addressed and the audit issues to be fixed and for avora we will be ready
to load test and simulate actual tutors and students."*

So at the end of this stage, four things are true:

1. The infrastructure is secure.
2. Everything that slipped through while Phases 0 to 9 were built is dealt with.
3. The launch check's issues are fixed.
4. Avora is ready for a load test with pretend tutors and students. **The load test itself comes
   after this stage, not inside it.**

**Why now.** The launch check of 10 October found that Avora is built, and the code is careful,
but it has never been run for real. No AI marking has ever completed in production, the server
loses uploaded files, and nothing tells anyone when something fails. The owner: *"i dont trust
the infra yet."*

**The rule for what gets fixed.** The owner, 11 October: *"anything that affects launch and 1k."*

- A problem that **stops launch** is fixed in this stage.
- A problem that **breaks on the way to 1,000 students** is fixed in this stage.
- A problem that **can wait** gets one written line: "fix later" or "leave it, and why". Nothing
  is dropped silently. Those lines are in section 6.

The same rule applies to the leftovers from Phases 0 to 9. Cleanup takes what is broken or
half-finished. It does not take new features.

Where two reviewers ranked the same problem differently, the stricter rank is used.

**How the work runs.** The owner: *"run and only stop when u need me for anything ur not sure
about and any high stake decision even if technical somewhat."* The builder runs without asking
for a go on each fix, and stops for exactly four things:

1. anything the builder is not sure about;
2. any high-stakes decision, even a technical one (section 4 lists them);
3. spending money: a subscription, a bigger server, real AI spend;
4. something only the owner can click, in Render, Vercel, Anthropic or another account.

**How a step is proved.** Every step ends with **"See it yourself"**: a short check the owner
does, or watches, with their own eyes. A step is not done because the tests pass or because the
builder says so.

**Limits.** Nothing is spent and nothing is changed in production without the owner's yes. The
builder assumes the owner wants the smallest paid setup that is safe; the owner has not said
this in so many words, so it is checked at the first spend.

**Not in this stage.** New features: the class reorganisation (B.4), the marking-rules line on
readiness (B.1), the Avora agent. The mobile app (Phase 12). The load test itself (11.6). The
second launch check. All of these come after.

**Where the detail is.** This repository is public. The launch check's reports are in the
owner's private audit folder and are never copied here. A finding is cited by its id only
(`OPS-01`, `SR-A`). A pull request, a commit message and this file say what a fix does, never
how a gap could be used. A builder who needs the mechanism reads the private report for that id.

**How big this is.** Honestly: it is the largest stage so far. The nine reviewers' reports hold
about 80 separate problems that stop launch or break by 1,000. The re-check of older findings
adds eleven that no reviewer had, and the phase leftovers add about a dozen more. Most are small. A few are not: the move to proper hosting, running
several markings at once, and deleting a child's data on request.

---

## 2. The twelve steps at a glance

1. **Your quick checks, and a safety copy.** A few things only the owner can look at, and one
   backup taken before anything is touched.
2. **Make marking work.** Today it fails on every submission.
3. **A proper home.** Files that survive, a server that stays awake, a backup we have restored.
4. **See every failure.** Alerts, a record of errors, and a list of work that failed.
5. **The first rehearsal.** A pretend class goes through the whole loop, then it is broken on
   purpose. The first real proof, and the first real numbers.
6. **Close the doors.** Who can sign up, how much anyone can spend, and who can see what.
7. **Everyday gaps.** Passwords, class links, deleting a lesson, uploading from a phone.
8. **Handle a crowd.** Many markings at once, correct when two things happen together, old data
   cleaned out.
9. **What it costs.** Measure the real AI cost, count it correctly, bring it down.
10. **Children's data and the privacy page.** The page says only what is true, and what it
    promises exists.
11. **Leftovers and true documents.** What slipped through in Phases 0 to 9, and documents that
    no longer match the code.
12. **The final rehearsal.** Everything again, end to end. Then Avora is ready to be load tested.

Steps 1 to 5 go in that order. Steps 6 to 11 can overlap. Step 12 is last.

---

## 3. The steps

### Step 1. Your quick checks, and a safety copy

**For the owner**

- **What it does.** Settles a handful of facts that only you can see, and takes one copy of the
  database before anything else is touched.
- **Why.** Several later choices depend on these facts. And nobody should start moving a
  database that has no copy.
- **What I need from you** (about half an hour, one item at a time, never a secret value read
  out):
  - the plan name shown for the server and for the database in Render;
  - that the login secret in Render exists and is not the placeholder;
  - that the AI key is set, and a monthly spending limit is set in the Anthropic console;
  - that the database password shared on 8 October has been changed;
  - two-step login, and a second person or a recovery route, on GitHub, Render, Vercel, the
    domain and the AI account.
- **See it yourself.** I show you the safety copy opened in a spare database, with the same
  number of tutors, students and marks as the real one.

**For the builder**

- Record the Render plan names and the database's storage and creation date. Known on
  11 October: the owner pays $6.30 a month for the database, so it is a paid plan and does not
  expire. Whether that plan keeps restorable backups is **not confirmed**.
- Take a manual dump before any change, restore it into a throwaway Postgres, count rows in
  `users`, `submissions`, `question_marks`. The dump holds children's records: encrypted, off
  the repo, off any shared drive.
- Turn on branch protection so a failing change cannot ship (`CFG-7`). It costs nothing.
- Findings: `SA-04` / `SR-J` (the check; the code fix is in step 6), `GH-10`, `CFG-7`, `C-1`
  (the provider-side limit only; the real limits are step 6), `OPS-20` (first backup).
- **Stop:** anything in a dashboard is the owner's click. Never ask for a secret's value.

### Step 2. Make marking work

**For the owner**

- **What it does.** Fixes the one setting that makes every AI marking fail, and makes sure a
  stuck or broken AI call cannot freeze everything else.
- **Why.** Marking is the heart of the homework loop. Nothing else can be measured or rehearsed
  while it fails. It went unnoticed because the tests use a pretend AI.
- **What I need from you.** Nothing.
- **See it yourself.** The first eyes-on proof is at the end of step 3, on the new home: you
  hand in one photographed page as a pretend student and watch the mark appear.

**For the builder**

- Fix the marking call (`OPS-01` / `CAP-1`). Pin the AI library version with a lock file.
- Add a test that builds the **real** client against a mock transport, so the library's own
  checks run in the suite. No test calls a real provider (`QA-8`); `QA-7` still governs logic
  tests.
- Give every AI call and every job a time limit, and stop retrying errors that can never
  succeed (`OPS-09` / `CAP-7`).
- Check the other surfaces' output limits against the model's default thinking, which the
  launch check could not verify (`C-7`, second half): a short limit may cut an answer off.
- Marking handlers stay safe to re-run (`BE-6`); never overwrite a tutor-finalized mark.
- **Stop:** any change to the marking prompt, the marking model or the thinking setting is
  high-stakes. It bumps the prompt version (`AI-7`), keeps the untrusted-page rule (`SEC-20`),
  and waits for step 9's side-by-side check.

### Step 3. A proper home

**For the owner**

- **What it does.** Moves Avora off the free server onto a setup where students' files are
  stored safely, the server stays awake, an update can be undone, and the database has a backup
  that has actually been restored once.
- **Why.** On the free server every restart deletes every uploaded page, and background work
  stops whenever it sleeps.
- **What I need from you.**
  - a yes to the subscriptions, asked one at a time with the price at that moment;
  - where students' data should be stored (the region). It is chosen once, when the services are
    created, and it is hard to change later;
  - a few clicks in Render and Cloudflare that I will walk you through.
- **See it yourself.** You upload a page. I restart the server. You open the same page again.
  Then I show you last night's backup opened in a spare database.

**For the builder**

In the launch check's order. Build the new setup beside the old one and switch when it is
proved; there are no real users, so this is the cheapest the move will ever be.

1. The security-header change that lets the browser load stored files, **before** storage is
   switched (`CFG-8`). Test in Chrome and in Safari on a phone.
2. Object storage on (`STORAGE_BACKEND=s3`), a bucket-limited key, a CORS rule for the site
   (`OPS-12`, `C-10`, `C-9`).
3. A paid, always-on server. The smallest size is enough for the rehearsal and too small for
   real students (`CFG-9`, `SA-03`).
4. In the same change, migrations run as a pre-deploy step, so going back a version still
   starts (`OPS-03`). Keep migrations add-only from here.
5. Database: plan, region, backups, and **one restore rehearsed into a new database**, timed
   (`OPS-20`, `P-12`). Never restore over production.
6. Rows that point at files already lost: count them, and with the owner's yes clear the demo
   data rather than hand-edit keys. Add a read-only check that lists rows whose file is missing
   (`OPS-12`).
7. A second, small copy to try changes on, a visible build number, and updates without a gap
   in service (`OPS-14`). The server must refuse to report healthy with no usable database
   (`CFG-1`).
8. Prove a 20 MB upload passes through the site's proxy (`CFG-11`, unverified until now).
9. Make `render.yaml` describe what is really deployed, and correct the kill-switch comment
   that still promises a fallback that no longer exists (launch check, baseline report).

- Vercel's paid plan is needed before anyone is charged (`C-10`): the owner's yes, at that time.
- **Stop:** the region; the choice of file store; moving or recreating the database; clearing
  any data; every subscription.

### Step 4. See every failure

**For the owner**

- **What it does.** Makes Avora tell you when something breaks: an alert when it is down, a
  record of every error, and a list of work that failed, with a way to try it again.
- **Why.** Eighteen jobs failed in production and nobody knew. A student whose marking failed
  sees "being marked" forever.
- **What I need from you.** An email address or phone number for alerts, and one decision: how
  you look across all tutors at once (see "Stop" below).
- **See it yourself.** On the rehearsal setup I take the AI key away. You get an alert. The
  failed work appears in the list. I put the key back, press "try again", and it is marked.

**For the builder**

- An outside uptime check on `/api/v1/health/ready` that reaches the owner (`OPS-04`), and a
  health answer that can see the failures that really happen: a dead worker, a missing AI key
  or model, a growing queue (`OPS-05`, `CFG-2`).
- Logging at INFO with request, organization, user and job ids (`OPS-06`). Never log passwords,
  tokens, a student's content or a full prompt.
- Error tracking that pages on a new error.
- Permanently failed work can be listed and re-run without SQL (`OPS-07` / `CAP-8`). A job
  stranded by a restart is picked up in minutes, not hours (`OPS-02` / `CAP-11`; the launch
  check found the claimed recovery does not happen as documented).
- When marking fails for good, the student is told and the page stops asking; the tutor gets a
  plain message, not raw error text, and a "try marking again" action (`OPS-08`, `OPS-19`).
- A readiness AI failure is recorded as a failure, not shown as "not enough data yet"
  (`OPS-10`). This must not break `PROD-2`: absent data still reads as absent.
- Runbooks the owner can actually follow, corrected against the code (`OPS-13`).
- A record of sign-in events that matter: failed sign-ins, revoked sessions, password resets
  (`07-KG-6`).
- One page for the owner: what each alert means and what to do first. Today an alert would have
  nobody to reach and no next step (`11-KG-10`, `14-KG-8`).
- This is tasks 11.4 and 11.5 of the plan, done here. Metrics beyond these stay with the load
  test.
- **Stop:** the plan says the owner's view across all tutors is a separate internal tool, not a
  route in the product (`AV-3`, `AV-71`, 10.3). How the owner reads the failed-work list is that
  decision. Do not answer it by loosening a tenancy check (`PROD-4`, `SEC-7`).

### Step 5. The first rehearsal

**For the owner**

- **What it does.** One pretend tutor and a pretend class of five go through the whole loop on
  the new home, with real AI. Then I break it on purpose.
- **Why.** This is the first time Avora runs for real. Trust comes from watching it work.
- **The loop:** the tutor uploads a real booklet and mark scheme and sets homework; students
  hand in photographed handwritten pages from a phone; the AI marks them; the tutor reviews;
  readiness updates; a report goes out.
- **Broken on purpose:** the server is restarted, and the pages are still there; it is stopped
  in the middle of marking, and the work picks itself back up; the AI key is removed, and you
  are told.
- **What I need from you.** A real booklet, its mark scheme, a few photographs of handwritten
  answers, and a yes to a few dollars of real AI spend.
- **See it yourself.** You do one student's hand-in from your own phone. Then you get one page:
  what worked, what broke, how long each marking took and what each cost. **Measured**, for the
  first time.

**For the builder**

- Run the journeys the launch check says have never run together in a real browser: tutor
  sign-up and onboarding; class link and student join on a phone; past paper upload and
  extraction; a multi-page photographed hand-in from an iPhone; marking, auto-finalize or
  review, and the tutor opening the original page; marks, readiness, a remark and a redo; the
  parent link.
- Look at every recent screen in a real browser and on a phone, which has not been done since
  Phase 9 (`off-plan-16`).
- Record tokens, seconds and cost per marking from real calls. These replace the launch check's
  modelled figures and feed step 9.
- Messaging stays off unless the owner has decided otherwise (step 10), so no real parent can
  receive a test.
- Everything found is written down and sorted by the rule in section 1.
- **Stop:** real AI spend needs the owner's yes at the time. Anything the rehearsal breaks that
  is not already in a later step is raised before it is fixed.

### Step 6. Close the doors

**For the owner**

- **What it does.** Controls who can become a tutor, puts a ceiling on what any one account can
  spend or upload, makes sure one tutor's records can never reach another, and closes a batch
  of smaller gaps.
- **Why.** The launch check tried 800 times to read another tutor's data. It found one situation
  where the wall between two tutors does not hold. And today nothing limits sign-ups or AI
  spending.
- **What I need from you.** Three decisions, asked one at a time:
  - one workspace per student at launch (recommended: yes);
  - how new tutors are let in: open to anyone, by invitation, or approved by you;
  - whether a tutor's private notes about a student should ever be visible to that student or
    their parent.
- **See it yourself.** I show you a second pretend tutor trying to open the first tutor's
  student and getting nothing. Then a stranger's account hitting its daily ceiling and stopping.

**For the builder**

- The tenancy gap (`SR-A`, `SR-B`, `SR-C`, `SR-I`) and the note-visibility question (`SR-D` /
  `P-4`). Closing it removes a built behaviour, so it is a product decision before it is a
  patch. Add the missing two-organization test.
- Sign-up control and limits per account on AI calls, uploads and messages (`SA-01` / `C-2` /
  `SR-G`, `C-1`). They need an account status the owner can change first (`GH-2`).
- A file-count and re-submission ceiling, one pending marking per submission, and the case
  where an upload is replaced while its marking is running (`SA-07` / `C-4`, `DB-08`).
- A request-size limit, and uploads that are not read whole into memory (`SR-F` / `SA-08`,
  `CAP-5`; `SEC-17` is not met today on this path).
- The small safety batch, one pull request each: `SR-E` / `SA-05`, `SA-02` / `CAP-3`, `SA-03`
  / `CAP-4`, `SA-04` (refuse to start on the placeholder secret), `GH-5`.
- Sign-in protections: `SA-06`, `SA-11`. Any change that invalidates a credential bumps
  `users.token_version` (`SEC-1`).
- The marking trust boundary for photographed pages (`SA-09`).
- Make organization scoping a mechanism and not a habit: today it is applied query by query,
  and the dependency meant to enforce it is unused (`01-KG-3`, `RISK-7`).
- Dependencies and the container: a vulnerability check in CI, the library review, a container
  that does not run as root (`SA-14`, `SA-15`).
- Small items done here because they are in the same code: `SR-L`, `SR-M`, `SA-12`.
- Every change touching auth ships with a test of the negative case (`QA-12`), and a role gate
  goes in the signature, never the handler body (`BE-17`).
- At the end, re-run the launch check's own attack tests. All must fail to get in.
- **Stop:** the three owner decisions above; the numbers for each ceiling; any change to token
  lifetime or rotation; any change to what auto-finalizes; and where the browser keeps the
  sign-in token, which the legal checklist and the current design disagree on (`legal-17`).

### Step 7. Everyday gaps

**For the owner**

- **What it does.** Adds the ordinary things people will need in the first week and cannot do
  today.
- **Why.** A forgotten password is a dead end today, for tutors, parents and most students. A
  class link cannot be switched off. Deleting a lesson fails. A big phone photo can be refused
  with no explanation.
- **What gets done:**
  - reset a forgotten password, change a password, change an email address, close an account;
  - switch off a class link, and a removed student stays removed;
  - a parent can be unlinked from a child;
  - deleting a lesson works;
  - phone photos are shrunk before upload, with a progress bar and a clear message if a file is
    too big.
- **What I need from you.** A choice of email-sending service (password resets need one), and a
  yes to its cost.
- **See it yourself.** You reset your own password from the login page. You switch off a class
  link and try to use it. You delete a lesson.

**For the builder**

- Passwords and accounts: `SA-16` / `SR-H` / `CFG-10`, `GH-3`. Each bumps `token_version`
  (`SEC-1`). Fix the login page text that is wrong for students who joined by link.
- Class links and removal: `GH-1`. Invites stay bounded (`SEC-12`, `SEC-13`): mint with
  `build_invite()`, validate with `check_usable()`.
- Parent unlink: `P-8`.
- Lesson and timetable-slot delete on Postgres: `DB-11`. Add the test with foreign keys on.
- Phone upload: `GH-4`, and upload limits that match what the AI provider accepts (`C-8`).
- Email set-up, including the missing header (`GH-8`), with SPF and DKIM on the owner's domain.
- **Stop:** the email provider; how a student with no email resets a password (email, or a
  one-time code from the tutor) is a product choice.

### Step 8. Handle a crowd

**For the owner**

- **What it does.** Lets Avora mark many submissions side by side instead of one at a time,
  keeps it correct when two things happen in the same moment, and stops old data piling up.
- **Why.** Today there is one queue. If 1,000 students hand in on one evening, the last waits
  for hours. A class of 60 online at once can run the database out of connections.
- **What I need from you.** One decision: how long old working data and old uploaded files are
  kept before they are cleaned out.
- **See it yourself.** Thirty pretend hand-ins arrive at once on the rehearsal setup, and you
  watch several being marked together. This is a small demonstration, not the load test.

**For the builder**

This is the plan's Phase 11 except its last task, done here.

- 11.1, what is held in one process (`CAP-14`). 11.2, the concurrency audit, hotspot by hotspot
  (`DB-10`, `CAP-10`). 11.3, invariants enforced in Postgres and not only in Python (`DB-07`).
- More than one marking at a time, and a marking lane separate from the sweeps (`CAP-2` /
  `C-13`). The launch check's safe order: shared storage first (step 3), add the worker beside
  the in-process one, prove it, only then switch the in-process one off.
- Database connections: sized, and not held across an AI call (`DB-01` / `CAP-6`, `OPS-16`).
- Indexes for the hot lookups, built without locking a populated table (`DB-02`, `DB-03`,
  `DB-13`). Declared in the model as well as the migration (`DB-12`).
- Long lists are paged, not returned whole or cut off: the review queue (`DB-04`), the 48 list
  endpoints with no limit (`05-KG-3`), and the student list that stops at 500 (`05-KG-4`).
- Old rows are pruned or archived (`DB-05`, `OPS-17`). Uploaded files have a retention rule
  (`C-9`).
- The job queue is fair between tutors, so one tutor's large upload cannot hold up everyone
  else's marking (`DB-09`).
- A separate worker gets its own, narrower credentials (`F7`).
- The remaining case where a student's re-upload and a tutor's final mark land in the same
  instant (leftover from #145).
- The weekly sweep can keep up and cannot starve itself (`CAP-9`, `C-12`). Pages stop polling
  when there is nothing to wait for (`CAP-12`, `CAP-13`). The server sheds load instead of
  falling over (`CAP-16`).
- Run the whole test suite on a real Postgres. The launch check ran 89 of 126 files and left
  one unexplained lock hang; finish it and explain the hang.
- **Stop:** `AV-85` keeps production on one instance until 11.2 is complete. Switching on a
  second worker or a second server in production, any migration on a populated table, and any
  deletion of data are each raised first. Retention periods are the owner's.

### Step 9. What it costs

**For the owner**

- **What it does.** Replaces the estimated AI cost with a measured one, makes Avora count its
  own AI spending correctly, and then brings the cost down.
- **Why.** The launch check estimated about $17.50 per student a month, unmeasured, with a
  range from $2.80 to $61.50. The owner: *"17 dollars per student is wayyyyy too much."*
- **The cuts, least risky first:**
  - send the AI only the pages a homework covers, not the whole booklet;
  - limit how much the AI "thinks" before answering;
  - mark with a cheaper model, **only after you have seen the same pages marked both ways**.
- **What I need from you.** Your verdict on the side-by-side marks, and the price decision once
  the real cost is known.
- **See it yourself.** One page showing the cost of a marking before and after each cut, and
  the same handwritten pages marked by both models next to each other.

**For the builder**

- Measured tokens, seconds and cost come from step 5.
- Count cache tokens in the metering (`C-3`), record calls that have no tutor on the row
  (`C-14`), and reject a malformed price table loudly (`CFG-5`). A model with no price stays
  unpriced, never `$0` (`AI-17`).
- Pages sent per marking (`C-5`). The prompt cache earns its keep or is removed (`C-6`). The
  thinking setting (`C-7`).
- The model for each surface is named by surface, never in a call site (`AI-2`). The marking
  split is the plan's task 3.2 (`AV-124`).
- A small fixed set of real marked pages that every prompt or model change is checked against.
  None exists today, and the prompt has changed five times (`09-KG-1`, `RISK-10`). The
  side-by-side comparison for the owner is built on it.
- The landing page still shows the old price. It changes in its own code pull request once the
  price is final.
- The owner's usage view across accounts (`GH-2`, the plan's 10.1 and 10.3) uses the same
  answer as step 4's "Stop".
- Ask the AI provider for a higher monthly limit well before it is needed; one busy evening can
  exceed the starting limit and pause all AI until the next month.
- **Stop:** the marking model, the thinking setting and any prompt change are high-stakes and
  go to the owner with evidence. The published price (`C-15`) is the owner's alone.

### Step 10. Children's data and the privacy page

**For the owner**

- **What it does.** Makes the public privacy page say only what is true, and builds what it
  must be able to promise: removing a child's data on request, handing a family a copy of it,
  and not keeping it forever.
- **Why.** The page promises parental consent, deletion within 30 days, export and retention
  limits. None exist, and the page has no contact address. These are children's records.
- **What I need from you.**
  - a lawyer's reading. Nineteen questions are prepared. I do not give legal advice and I do
    not assume which country's rules apply;
  - the decision on the page: change the wording first, or build first;
  - whether a parent must agree before a child's account is made, and how age is asked;
  - whether WhatsApp and email messages are on at launch;
  - a real contact address for the page.
- **See it yourself.** You read the privacy page beside a checklist where every promise points
  to the thing in Avora that keeps it. Then you export a pretend student's data, delete that
  student, and see that nothing is left.

**For the builder**

- The page against the product, line by line (`P-11`). A real contact address in the site
  settings.
- Deletion and export (`P-3`): this is the plan's task 10.4, done here, with its security
  criteria unchanged: re-authenticate first, deliver out of band, write an audit row, clear
  object storage as well as rows, and **prove it with a test that nothing survives**.
- Age and consent at join (`P-1`). Retention, and photo metadata stripped on upload (`P-2`,
  `P-7`), including the old attempt and its pages kept when a tutor lets a student redo work. An AI label on AI-written text, and the auto-finalize setting (`P-10`). A record of
  who read what, and a way to reach affected families (`P-13`).
- Questions for the lawyer rather than for the builder: `P-9`, `P-14`.
- **Only if messaging is on at launch:** `P-5`, `CFG-3`, `CFG-4`, `C-11`, `SA-10`, `OPS-11`,
  `OPS-15`. Otherwise it stays dormant, which is its default, and these wait with it.
- **Stop:** everything in "What I need from you". Auto-finalize is settled product behaviour
  (`ADR-0009`); changing it is the owner's decision, not a privacy patch.

### Step 11. Leftovers and true documents

**For the owner**

- **What it does.** Works through the list of things that slipped while Phases 0 to 9 were
  built, by the same rule, and corrects the documents that no longer match the code.
- **Why.** Several documents describe a setup that is not the real one, and a document that is
  wrong is how the next mistake gets made.
- **What I need from you.** Your own outstanding jobs, as one short list (section 7), and a yes
  or no on each "can wait" line in section 6.
- **See it yourself.** The leftover list with every line marked fixed, or "later" with a reason.

**For the builder**

- The leftover list is section 7. Verify each item against the code before acting; several
  come from notes.
- The AI's difficulty and topic guesses for extracted questions shape topic scores and are
  never shown to the tutor (`01-KG-5`, against `PROD-1`).
- The two onboarding dead ends from Phase 9, and the two lists of who is in a class.
- Documents the launch check found untrue: the deployment blueprint against what runs; the
  runbooks that assume a server shell; the rule text on global subjects; the model names in
  `CLAUDE.md`; the "scheme always wins" text the owner reversed; the retry notes that disagree
  with each other; the Known Gaps that are fixed in code and still marked open.
- Documentation goes on the docs branch, never in a code pull request.

### Step 12. The final rehearsal

**For the owner**

- **What it does.** Runs the whole rehearsal again on the finished stage, re-runs the security
  attempts, restores a backup once more, and leaves Avora ready to be load tested.
- **Why.** Steps 6 to 11 changed a lot. The proof has to be of the finished thing.
- **What I need from you.** An hour to walk through it.
- **See it yourself.** The same loop as step 5, start to finish, on your phone and your laptop,
  with nothing on the "broke" side of the page.

**For the builder**

- The step 5 journeys again, now also as a small set of automated browser tests that run
  against the trial copy with a stand-in for the AI.
- The launch check's attack tests, all failing to get in. One more timed restore.
- Left ready for 11.6: the trial copy, sized like production; the stand-in AI switch proven
  (the provider's base-address setting, no code change); the list of what to measure. **The
  1,000-student fixture and the load scripts are 11.6's own work.**
- Write the one-page "ready for load test" note. Then the second launch check is still owed,
  after the whole plan, as the owner decided on 10 October.

---

## 4. When the builder stops

Everything not on this list is done without asking.

**The owner's decisions.** None is made for them.

| # | Decision | Step |
|---|---|---|
| D1 | The region where students' data is stored | 3 |
| D2 | Each subscription and each increase, at the time | 3, 7, 8 |
| D3 | How the owner looks across all tutors (a separate internal tool, per the plan) | 4, 9 |
| D4 | One workspace per student at launch | 6 |
| D5 | How new tutors are let in, and the ceiling on each account | 6 |
| D6 | Whether a tutor's private notes can reach a student or parent | 6 |
| D7 | The email-sending service, and how a student with no email resets a password | 7 |
| D8 | How long old data and old files are kept | 8, 10 |
| D9 | The marking model, after seeing the same pages marked both ways | 9 |
| D10 | The published price, once the cost is measured | 9 |
| D11 | The privacy page: reword first or build first; a lawyer's reading | 10 |
| D12 | Parental agreement and age at sign-up | 10 |
| D13 | Whether messages are on at launch | 10 |
| D14 | Each "can wait" line in sections 6 and 7 | 11 |
| D15 | The older questions still unanswered, listed in section 7 | 11 |

**High-stakes technical moments.** The builder stops and says plainly what is about to happen:

- any migration that changes a table already holding data in production;
- switching where files are stored; moving, recreating or restoring a database;
- deleting or pruning any data;
- any change to sign-in, tokens or session lifetime;
- any change to the marking prompt, the marking model, the thinking setting, or what
  auto-finalizes;
- switching on a second worker or a second server in production;
- anything that cannot be undone, and anything the builder is not sure about.

---

## 5. What this does to the rest of the plan

The owner's rule pulls work forward. Where a cleanup step is the same work as a later task, it
is done once, here.

- **Phase 10.** Task 10.4 (deletion and export) moves into step 10. The minimum of 10.1 and
  10.3 that steps 4 and 9 need moves with them. The tutor's own usage view (10.2) stays.
- **Phase 11.** Tasks 11.1 to 11.5 move into steps 4 and 8. **Phase 11 keeps the load test
  (11.6)**, which is still the last thing before the mobile app.
- **B.2** (the move off the free server) is step 3.
- **Phase 12** and the features in "Before Phase 10" are unchanged and come after.

---

## 6. What can wait

Each finding the launch check ranked "later", with the line proposed for it. The owner says yes
or no to each in step 11. "With step N" means it is small and sits in code that step already
touches, so it is done then.

| Finding | What it is about | Proposed |
|---|---|---|
| `OPS-16` | Database connection health checks | With step 8 |
| `OPS-17` | Old job rows never cleaned | With step 8 |
| `OPS-18` | Some background jobs fail quietly | Covered by step 4's failed-work list; anything left, later |
| `OPS-19` | Raw error text shown to a tutor | With step 4 |
| `OPS-20` | Backup and restore | Done in steps 1 and 3 |
| `OPS-21` | A message can be sent twice | Leave: by design. Look again when messaging is switched on |
| `DB-03` | Sign-in lookups and their index | With step 8 |
| `DB-06` | Roster reads look at every old snapshot | Later. Watch it in the load test |
| `DB-09` | One queue shared by every tutor, first come first served | Step 8. The older review ranks it "breaks by 1,000", and the stricter rank is used |
| `DB-12` | Differences between the test database and the real one | Partly with step 8; the rest later |
| `DB-14` | A correction to an earlier note, nothing to fix | With step 11 (documents) |
| `CAP-13` | The site downloads as one large file for every role | Later |
| `SR-L` | A missing ownership check on three write paths | With step 6 |
| `SR-M` | A library update | With step 6 |
| `SA-12` | Public pages that describe the system | With step 6 |
| `SA-13` | Sign-in and invite pages reveal whether an account exists | Later. Step 6's limits reduce it |
| `SA-14` | Pinned versions, the container's user, a security check in CI | Steps 2 and 6. Stricter rank used |
| `SA-15` | A review of third-party libraries | Step 6, then every quarter. Stricter rank used |
| `C-14` | Small unmetered AI paths | Metering part with step 9; the rest later |
| `P-6` | Meeting integrations store other people's names | Later, and before the Zoom and Google apps are registered |
| `P-7` | AI-written text about a child is kept forever | With step 10 (retention) |
| `P-9` | Details collected and never used | A question for the lawyer in step 10 |
| `P-14` | A child's full name is sent to the AI provider | A question for the lawyer in step 10 |
| `P-15` | A shared device stays signed in for 30 days | Later. Related to step 6's sign-in work |
| `CFG-5` | A mistyped price table is ignored silently | With step 9 |
| `CFG-6` | Changing the login secret can orphan stored connections | Later. Written into the runbook in step 4 |
| `GH-6` | Mocks cannot be created from the product | The owner's decision: mocks in or out |
| `GH-7` | "Next lesson" and the day the week starts | Later. The week start is the owner's choice |
| `GH-8` | A missing header on outgoing email | With step 7 |
| `GH-9` | Bringing a tutor's existing material in, one file at a time | Later |
| `GH-10` | One person holds every account | Done in step 1 |
| `GH-11` | Nothing marks the end of a school year | Later. The owner's decision |

The launch check also re-checked about 240 older findings. Its 115 open "later" rows are listed
by id in the private ledger and are reviewed as one batch in step 11.

---

## 7. Leftovers from Phases 0 to 9

Compiled from the status notes of each phase on 11 October. **"Checked"** means it was seen in
the code that day; everything else comes from notes and is verified before anyone acts on it.

**7.1 Fixed in this stage**

| Leftover | Step |
|---|---|
| A student's re-upload and a tutor's final mark landing in the same instant (checked) | 8 |
| The old attempt and its pages, kept after a redo, have no rule for how long they stay | 10 |
| For a student shared between two tutors, readiness settings follow the wrong tutor | 6 (goes away with D4) |
| Two lists of who is in a class, used by different screens, can disagree | 11, after the owner's answer |
| The AI's difficulty and topic guesses are never shown to the tutor (checked) | 11 |
| Two onboarding dead ends: an admin or second tutor pushed into set-up, and a class that cannot get a plan stuck in set-up for good | 11 |
| No recent screen has been looked at in a browser or on a phone | 5 and 12 |
| No fixed set of marked pages to check a prompt or model change against | 9 |
| The landing page shows a price the owner has replaced (checked) | 9 |
| The container runs as root; no dependency lock file or vulnerability check (checked) | 2 and 6 |
| Organization scoping depends on each query remembering it (checked) | 6 |
| Database rules that live only in code | 8 |

Already covered by steps 2, 3, 4 and 6 and so not repeated: marking jobs failing for want of an
AI key, production on the free server, no request ids or alerts, and no limit on AI use per
account.

**7.2 Can wait** (proposed; the owner says yes or no to each in step 11)

| Leftover | Proposed |
|---|---|
| The link in the weekly message is lost if the reader has to sign in first | Later |
| Weekly-send loose ends: no retry for one reader's failure; two cases that only arise with a shared student | With step 10 if messaging is on; the shared-student cases go away with D4 |
| "Let them redo" keeps the tutor's override history as a record inside one row, not in the live tables | The owner's answer is still owed (asked twice) |
| Redo side effects: the student is not told; reminders treat the work as not handed in until they hand in again | Later |
| Deleted-class loose ends: a queued message still sends; some access checks have no test of their own | Add the missing tests with step 6; the rest later |
| Topic Mastery switched off may still drive topic bars and class means | The owner's answer is still owed |
| Three AI surfaces build their own picture of a student, so two screens could differ | Later |
| Past-paper extraction ignores the tutor's marking-style notes (checked) | Later |
| Smaller Phase 9 gaps: a readiness refresh after "taught before"; the "marked for you" count; unsaved drafts lost on a subject switch; keyboard handling in the More menu | Later |
| Two Phase 7 calls the owner has not confirmed | The owner's answer is still owed |
| Accessibility: no focus trap in the modal, no skip link, loading and errors not announced (checked) | Later. Note: the standards document marks two of these as blocking, so this one deserves a real yes or no |
| Engineering debt: type checking scope, hand-written API types, four large pages with no tests | Later |
| About 30 merged branches never deleted, and one old open pull request | Step 11, with the owner's yes before anything is deleted |

Not cleanup, because they are features: invites by message, web push, a student's own weekly
paragraph.

**7.3 The owner's outstanding jobs**

| Job | When |
|---|---|
| Confirm the AI key is set in Render | Step 1 |
| Change the database password shared on 8 October | Step 1 |
| The subscriptions for the new home | Step 3 |
| Readiness recompute on the server (it needs a server shell, which the free server does not have) | After step 3; the builder runs it with the owner's yes |
| Confirm earlier migrations reached production | Replaced by step 3: the new home is checked against the latest migration |
| Look at the new screens on a phone | Step 5 |
| Move the repository out of the iCloud-synced Desktop (it creates duplicate files) | Step 11 |
| Register the Zoom and Google apps | Can wait until attendance import is wanted. The set-up guide was a scratch file and may need rewriting |
| Meta and WhatsApp registration, templates and settings | Only if messages are on at launch (D13) |

**7.4 Older questions still unanswered** (D15)

1. Do shared students exist at all? (Answered by D4.)
2. Is the redo's stored record enough for the rule that an override is never lost?
3. What should switching Topic Mastery off do?
4. Which list of class members is the true one?
5. The two Phase 7 calls: lessons that ended before a plan was accepted never auto-record, and
   deleting a recorded lesson cancels its plan slot.
6. Should the pricing pull request (#151) go to the default branch or the docs branch?

**7.5 Documents to correct**

- The deployment blueprint against what really runs, and its kill-switch comment.
- The runbooks that tell the reader to use a server shell.
- The claim that a crashed worker's job is recovered by its restart.
- The model names in `CLAUDE.md` and the routing decision record; the table and module counts.
- The plan text the owner reversed ("the scheme always wins"), and the readiness next-steps
  note left as an amendment.
- The retry notes that disagree across three documents; the reason given for the subject
  scoping rule.
- Known Gaps that the code has closed and the documents still list as open (eleven rows).
- The API and module lists for Phases 7 to 9 and the coherence pass, which were never written.
- Two decision records that share one number.

---

## 8. Done when

- Every step's "See it yourself" has been done by the owner.
- Every finding ranked "stops launch" or "breaks by 1,000" is fixed, or the owner has decided
  otherwise in writing.
- Every "can wait" line in section 6 has a yes or a no.
- The final rehearsal passes with nothing on the "broke" side.
- The "ready for load test" note is written, and 11.6 can start.

---

## 9. Ledger: which finding is handled in which step

Ids only. The private audit folder holds what each one means. Two ids on one line with "/" are
the same problem found by two reviewers. Ids such as `07-KG-6`, `RISK-7`, `F7` and `off-plan-16`
are older findings that the launch check re-checked and found still open; the private ledger
maps every one of the older rows to a finding here.

| Step | Findings |
|---|---|
| 1 | `SA-04` / `SR-J` (check), `GH-10`, `CFG-7`, `C-1` (provider limit), `OPS-20` |
| 2 | `OPS-01` / `CAP-1`, `OPS-09` / `CAP-7`, `C-7` (output limits), `SA-14` (pinning) |
| 3 | `OPS-12` / `C-10`, `C-9`, `CFG-8`, `CFG-9`, `CFG-11`, `OPS-03`, `OPS-14`, `OPS-20`, `P-12`, `CFG-1` |
| 4 | `OPS-04`, `OPS-05`, `CFG-2`, `OPS-06`, `OPS-07` / `CAP-8`, `OPS-02` / `CAP-11`, `OPS-08`, `OPS-19`, `OPS-10`, `OPS-13`, `07-KG-6`, `11-KG-10` / `14-KG-8` |
| 5 | `off-plan-16`; otherwise it proves steps 2 to 4 and measures for step 9 |
| 6 | `SR-A`, `SR-B`, `SR-C`, `SR-I`, `SR-D` / `P-4`, `SA-01` / `C-2` / `SR-G`, `C-1`, `GH-2` (status), `SA-07` / `C-4`, `DB-08`, `SR-F` / `SA-08`, `CAP-5`, `SR-E` / `SA-05`, `SA-02` / `CAP-3`, `SA-03` / `CAP-4`, `SA-04` (code), `GH-5`, `SA-06`, `SA-11`, `SA-09`, `SR-L`, `SR-M`, `SA-12`, `SA-14`, `SA-15`, `01-KG-3` / `RISK-7`, `legal-17` |
| 7 | `SA-16` / `SR-H` / `CFG-10`, `GH-3`, `GH-1`, `P-8`, `DB-11`, `GH-4`, `C-8`, `GH-8` |
| 8 | `CAP-14`, `DB-10`, `CAP-10`, `DB-07`, `CAP-2` / `C-13`, `DB-01` / `CAP-6`, `OPS-16`, `DB-02`, `DB-03`, `DB-13`, `DB-12`, `DB-04`, `05-KG-3`, `05-KG-4`, `DB-05`, `OPS-17`, `C-9` (retention), `DB-09`, `F7`, `CAP-9`, `C-12`, `CAP-12`, `CAP-13` (polling), `CAP-16` |
| 9 | `C-3`, `C-14`, `CFG-5`, `C-5`, `C-6`, `C-7`, `C-15`, `GH-2` (usage view), `09-KG-1` / `RISK-10` |
| 10 | `P-11`, `P-3`, `P-1`, `P-2`, `P-7`, `P-10`, `P-13`, `P-9`, `P-14`; if messaging is on: `P-5`, `CFG-3`, `CFG-4`, `C-11`, `SA-10`, `OPS-11`, `OPS-15` |
| 11 | `01-KG-5`; the leftovers in section 7; the document corrections; `DB-14` |
| 12 | none of its own; it re-proves everything |
