# Phase 8 — Intelligence and communication: status

**Built 2026-10-05, PRs #128–#134.** This records what shipped, the owner decisions that
changed the plan, and what is still owed. The plan itself is in
`avora-new-state-august-16.md` (Phase 8).

## Owner decisions that changed the plan (2026-10-05)

| Decision | Effect |
|---|---|
| **WhatsApp is the main channel; email is the fallback.** Recipients: parents, students and tutors. | 8.1 became a channel-agnostic notifications module, not an email module. Logins and password resets stay email-based. |
| **STOP stops every channel**, not only WhatsApp. | An opt-out on any contact blocks all sends to that person. |
| **Build everything that does not need Meta approval.** Avora is not yet registered as a business. | The WhatsApp channel ships dormant: with `WHATSAPP_*` unset a notification ends `channel_unconfigured` and nothing fails. |
| **"Everything revolves around the teaching plan."** | The tutor's weekly send and the class report lead with plan position. |

## What shipped

| Task | PR | What |
|---|---|---|
| 8.6 | #128 | Tutor class report and a top-level **Reports** tab. `GET /groups/{id}/report`. Deterministic, no AI. |
| 8.2 (facts) | #129 | `services/weekly_send_facts.py`: tutor, student and parent fact sets; `week_window` on the organization's clock. |
| 8.1 | #130 | Migration **0065**. `contact_points`, `notification_preferences`, `notifications` (outbox), `whatsapp_opt_outs`; org `weekly_send_weekday`, `weekly_send_hour`, `ai_language`. WhatsApp Cloud API and SMTP adapters, the `send_notification` job, the WhatsApp webhook, contact and preference endpoints, `GET /notifications/undelivered`. |
| 8.2–8.4 | #131 | Migration **0066** `weekly_sends`. Sweep and per-organization build; read API; the link on each home page and the page that shows a send. |
| 8.1 screens | #132 | Student page contacts with confirm; Settings → Messages; account-page preferences. |
| 8.5 | #133 | `services/notifications/triggers.py`: homework set, marked work ready, homework due, lesson reminder, review nudge. |
| sweep | #134 | Review-nudge wording. |

## Rules this phase established

- **Nothing is sent to an unconfirmed address.** A tutor sees the saved address shown back and
  confirms it; changing it clears the confirmation (threat review F5).
- **An opt-out belongs to the number**, not to a contact row (`whatsapp_opt_outs`): it holds for a
  number we have no contact for yet and survives re-entry. Only the person's own START lifts it.
- **Fact sets and notification params carry numbers, names and states only** — never a student's
  free text (threat review F9). A test seeds a sentinel into every free-text column and asserts
  it reaches no send.
- **One writer** (AV-99): the weekly send copies stored narrative rows; it has no generator.
- **Sweeps, not chains**, with the successor committed first — as `services/narrative.py`.
- **A message never fails the work it describes**: announcements run in their own savepoint.
- **The outbox is at-least-once and does not replay** what ended `channel_unconfigured`,
  `no_channel` or `suppressed`.

## Kill switches

`WEEKLY_SEND_ENABLED`, `MESSAGE_TRIGGERS_ENABLED`, `NARRATIVE_ENABLED`. Each stops new work and
leaves stored rows readable; the sweeps keep re-arming so switching back on needs no restart.

## Owner jobs before WhatsApp goes live

1. Meta Business verification and a dedicated number not on personal WhatsApp.
2. WhatsApp Business Platform (Cloud API): set `WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` on Render, and
   `APP_BASE_URL` to the app's address.
3. Point Meta's webhook at `/api/v1/webhooks/whatsapp`.
4. Submit the templates. Names and text are `meta_submission_text` in
   `services/notifications/templates.py`.
5. Check `PERMANENT_CODES` in `services/notifications/whatsapp.py` against Meta's error table.
6. Optional email fallback: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
   `SMTP_FROM`.

## Not built

- **Invites by message** (part of 8.5, AV-61): `notify()` needs an existing account.
- **8.7 web push**: demoted by the WhatsApp decision; not started.
- **A paragraph in the student's weekly send**: the only stored narrative about a learner is
  written to their parent.
- **The `/weekly/:id` deep link is lost through the login redirect.**
- **Reviews**: #131–#133 had no independent reviewers (subagent limit); they were self-reviewed.
- **Constitution updates** (GOV-1) for the new endpoints, tables and rules above.
