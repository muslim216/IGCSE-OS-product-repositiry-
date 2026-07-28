"""Suggesting which app student a Classroom student is.

Deliberately deterministic and boring: a wrong mapping files one student's
marks against another's record, so suggestions are only ever pre-selected in
the UI and never persisted without the tutor saving them.
"""

import re

from app.models import User


def _normalise(name: str) -> frozenset[str]:
    """Lowercase name into a token set, so word order and punctuation don't matter."""
    cleaned = re.sub(r"[^\w\s]", " ", name.lower())
    return frozenset(t for t in cleaned.split() if t)


def suggest_matches(
    google_students: list[dict], members: list[User]
) -> dict[str, int]:
    """Map google_user_id -> app user id, at most one suggestion per app student.

    `google_students` entries carry `id`, `name` and optional `email`.
    """
    remaining = list(members)
    suggestions: dict[str, int] = {}

    def take(student: User, google_id: str) -> None:
        suggestions[google_id] = student.id
        remaining.remove(student)

    def only(candidates: list[User]) -> User | None:
        """Ambiguity is worse than no suggestion — leave those for the tutor."""
        return candidates[0] if len(candidates) == 1 else None

    # Email first — it's the only genuinely unique signal.
    for gs in google_students:
        email = (gs.get("email") or "").strip().lower()
        if not email:
            continue
        match = only([m for m in remaining if (m.email or "").lower() == email])
        if match:
            take(match, gs["id"])

    # Then exact name, then a token-set comparison that tolerates reordering
    # ("Ali, Ahmed") and dropped middle names.
    for gs in google_students:
        if gs["id"] in suggestions:
            continue
        name = (gs.get("name") or "").strip()
        if not name:
            continue
        match = only([m for m in remaining if m.name.strip().lower() == name.lower()])
        if match:
            take(match, gs["id"])
            continue

        tokens = _normalise(name)
        if not tokens:
            continue
        def matches(member: User) -> bool:
            other = _normalise(member.name)
            if other == tokens:
                return True
            # A subset covers a dropped middle name, but needs enough overlap
            # that two unrelated people sharing a first name don't match.
            return len(other & tokens) >= 2 and (other <= tokens or tokens <= other)

        match = only([m for m in remaining if matches(m)])
        if match:
            take(match, gs["id"])

    return suggestions
