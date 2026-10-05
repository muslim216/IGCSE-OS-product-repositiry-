"""One registry for every notification kind.

WhatsApp business-initiated messages must use a template Meta has approved, so
the copy exists in two places that have to agree: the approved template and the
email fallback. Both live here, next to each other, so they cannot drift. The
`meta_submission_text` is the exact body the owner submits to Meta; its
`{{N}}` placeholders are the params in order, with the link always last.

Params are numbers, enumerable values and short names only — never a student's
free text (threat review F9). That is also what makes a template safe to fill
without escaping.
"""

import re
from dataclasses import dataclass

from app.models import NotificationKind

#: The WhatsApp template language for an organization's `ai_language`.
WHATSAPP_LANGUAGES = {"en": "en", "ar": "ar"}

_MAX_PARAM_LENGTH = 60
_PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")


@dataclass(frozen=True)
class Template:
    kind: NotificationKind
    whatsapp_name: str
    #: Ordered body parameters. The link is appended after these.
    params: tuple[str, ...]
    email_subject: str
    #: `str.format` text over `params` plus `link`.
    email_body: str
    meta_submission_text: str

    @property
    def whatsapp_param_count(self) -> int:
        return len(self.params) + 1


def _t(
    kind: NotificationKind,
    params: tuple[str, ...],
    subject: str,
    body: str,
    meta_text: str,
) -> Template:
    return Template(
        kind=kind,
        whatsapp_name=f"avora_{kind.value}",
        params=params,
        email_subject=subject,
        email_body=body + "\n\nOpen Avora: {link}\n",
        meta_submission_text=meta_text,
    )


TEMPLATES: dict[NotificationKind, Template] = {
    t.kind: t
    for t in (
        _t(
            NotificationKind.weekly_send,
            # `whose` is a possessive the sender builds — "Sara's", "your",
            # "your classes'" — because one template serves all three readers.
            ("whose", "lessons_count", "homework_done"),
            "This week on Avora",
            "Here is {whose} week on Avora: {lessons_count} lessons and "
            "{homework_done} homework pieces handed in.",
            "Here is {{1}} week on Avora: {{2}} lessons and {{3}} homework pieces handed in. "
            "See the full picture: {{4}}",
        ),
        _t(
            NotificationKind.homework_set,
            ("student_name", "subject_name", "due_date"),
            "New homework for {student_name}",
            "{student_name} has new {subject_name} homework, due {due_date}.",
            "{{1}} has new {{2}} homework, due {{3}}. Details: {{4}}",
        ),
        _t(
            NotificationKind.homework_due,
            ("student_name", "subject_name", "due_date"),
            "Homework due soon for {student_name}",
            "{student_name}'s {subject_name} homework is due {due_date}.",
            "{{1}}'s {{2}} homework is due {{3}}. Details: {{4}}",
        ),
        _t(
            NotificationKind.marked_work_ready,
            ("student_name", "subject_name"),
            "Marked work is ready for {student_name}",
            "{student_name}'s {subject_name} work has been marked and is ready to see.",
            "{{1}}'s {{2}} work has been marked and is ready to see: {{3}}",
        ),
        _t(
            NotificationKind.lesson_reminder,
            ("subject_name", "start_time"),
            "Lesson reminder",
            "A reminder that your {subject_name} lesson starts at {start_time}.",
            "A reminder that your {{1}} lesson starts at {{2}}. Details: {{3}}",
        ),
        _t(
            NotificationKind.review_queue,
            ("pending_count",),
            "Work waiting for your review",
            "You have {pending_count} marks waiting for your review.",
            "You have {{1}} marks waiting for your review: {{2}}",
        ),
        _t(
            NotificationKind.invite,
            ("tutor_name",),
            "You have been invited to Avora",
            "{tutor_name} has invited you to Avora.",
            "{{1}} has invited you to Avora. Join here: {{2}}",
        ),
        _t(
            NotificationKind.contact_confirm,
            ("tutor_name",),
            "Your contact details on Avora",
            "{tutor_name} added this contact for Avora updates. "
            "Reply STOP at any time to turn them off.",
            "{{1}} added this contact for Avora updates. Reply STOP at any time to turn "
            "them off. Details: {{2}}",
        ),
    )
}

_BY_NAME = {t.whatsapp_name: t for t in TEMPLATES.values()}


def template_for(kind: NotificationKind) -> Template:
    return TEMPLATES[kind]


def template_by_name(name: str) -> Template | None:
    return _BY_NAME.get(name)


def clean_params(kind: NotificationKind, params: dict) -> dict[str, str]:
    """Exactly the template's params, as short single-line strings.

    A missing key is a caller bug and raises; extra keys are dropped, so free
    text a caller passes by accident is never stored or sent. Newlines are
    flattened because WhatsApp rejects them in a body parameter.
    """
    tpl = template_for(kind)
    missing = [k for k in tpl.params if k not in params]
    if missing:
        raise ValueError(f"{kind.value} notification is missing params: {', '.join(missing)}")
    return {k: " ".join(str(params[k]).split())[:_MAX_PARAM_LENGTH] for k in tpl.params}


def ordered_values(tpl: Template, params: dict, link_url: str) -> list[str]:
    return [str(params[k]) for k in tpl.params] + [link_url]


def render_email(tpl: Template, params: dict, link_url: str) -> tuple[str, str]:
    values = {k: str(params[k]) for k in tpl.params}
    return (
        tpl.email_subject.format(**values),
        tpl.email_body.format(link=link_url, **values),
    )


def meta_placeholder_numbers(text: str) -> list[int]:
    return [int(n) for n in _PLACEHOLDER.findall(text)]
