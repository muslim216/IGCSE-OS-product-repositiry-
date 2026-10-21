"""A deterministic scan of typed answers, run before the marking call (`AV-93`).

Typed answers auto-finalize exactly as photographed work does (`AV-91`) — the
trust rule does not change by channel. But typed input is a materially easier
injection channel than handwriting: perfect fidelity, arbitrary length, and
marks come back afterwards, so a student can refine an attempt across
submissions.

**This is crude and bypassable, and that is understood.** It is also the only
control in this path that does not depend on the model's own judgement about
the attacker's text. A hit sets `needs_review` for that one submission and the
AI's confidence is not consulted — so the cheapest attacks cost a tutor's glance
rather than a mark. `AV-93` says explicitly: do not replace it with a model call.

A pure function over the text (`E20`): no session, no I/O, no settings. That is
what makes it testable exhaustively and what stops it growing into a service
with its own opinions.

**Known and accepted, per the plan: a second AI call to detect injection, a
mark-value cap on auto-finalize, and calibration metrics were all offered and
declined.** Declining calibration means there is no way to detect this being
exploited. That is a deliberate position, not an oversight — do not add them
back without asking.
"""

import re
import unicodedata
from dataclasses import dataclass

#: Patterns that have no business in an answer to an exam question.
#:
#: Chosen for what a student would have to *deliberately* type, not for what
#: might appear by accident: every one addresses the marker as a system rather
#: than answering the question. A false positive costs a tutor one glance at
#: work that was going to be marked anyway; a false negative costs a mark that
#: counts. The asymmetry is why the list errs wide.
#:
#: Kept as (name, pattern) so a hit can say *which* rule fired — a boolean
#: alone leaves a tutor with "something was odd about this" and nothing to look
#: at (`PROD-1`: no signal without its provenance).
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("instruction-override", r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\b"),
    (
        "instruction-override",
        r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|rules?)\b",
    ),
    (
        "role-address",
        r"\b(you\s+are|act\s+as|pretend\s+to\s+be)\s+(an?\s+)?(ai|assistant|marker|examiner)\b",
    ),
    (
        "role-address",
        r"\b(system|assistant|user)\s*:\s*",
    ),
    ("mark-instruction", r"\b(award|give|assign)\s+(me\s+)?(full|maximum|max|all)\s+marks?\b"),
    ("mark-instruction", r"\bmark\s+this\s+(as\s+)?(correct|right|full)\b"),
    ("authority-claim", r"\b(the\s+)?tutor\s+(has\s+)?(already\s+)?(approved|confirmed|said)\b"),
    ("authority-claim", r"\bpre[- ]?approved\b"),
    ("prompt-scaffolding", r"</?(system|instructions?|prompt)>"),
    ("prompt-scaffolding", r"\[/?(INST|SYSTEM|PROMPT)\]"),
    # SA-09: text imitating the fence marking.py wraps the answer in, so what
    # follows looks like it is outside the student's work.
    ("fence-imitation", r"\b(begin|end)\s+student\s+typed\s+answer"),
    # The colon is required: "the teacher's comment in the margin" is a student
    # describing feedback, "Examiner's note: ..." is addressing the marker.
    ("role-address", r"\b(examiner|marker|grader|teacher)\W{0,2}s?\s+(note|comment|override)\s*:"),
    ("role-address", r"\[\s*(marker|examiner|grader|system)\s*:"),
    # `=` only: "confidence: high" is ordinary prose in a reflection or a
    # statistics answer; the bracketed form is caught by the rule above.
    ("confidence-claim", r"\bconfidence\s*=\s*(high|medium)\b"),
    # An object is required (this/me/it/my ...): "assign the maximum score to the
    # outlier" is a method step, "give this the top mark" is addressed to the marker.
    (
        "mark-instruction",
        r"\b(give|award|assign|grant)\s+(this|me|it|my\s+\w+)(\s+answer)?\s+(the\s+)?"
        r"(top|highest|maximum|full)\s+(marks?|scores?)\b",
    ),
    # About the answers or the marking only: "the result is confirmed correct by
    # repeating the titration" is chemistry, not a note to the marker.
    (
        "mark-instruction",
        r"\banswers?\W+(\w+\W+){0,3}?(is|are)\s+(verified|confirmed)\s+(as\s+)?correct\b",
    ),
    # Run on the Arabic-folded text (see _normalise): hamza forms are plain alef,
    # ة is ه, ى is ي and marks are gone. The leading boundary stops a match
    # inside a longer word such as المنحنى.
    (
        "mark-instruction",
        r"(?<!\S)(اعط|امنح)\w*(\s+\S+){0,4}?\s+ال(درجه|علامه|درجات|علامات)\s+ال(كامله|تامه|نهائيه|كاملات)",
    ),
)

#: Spaced-out letters ("i g n o r e") defeat `\b` patterns, so a few of the
#: worst phrases are also looked for in the text with everything but letters and
#: digits removed, so "i.g.n.o.r.e" and "END STUDENT-TYPED ANSWER" collapse too.
#: No `\b` here by design; that is also why the list is short — collapsed text
#: can join the end of one word to the start of the next by accident.
_COLLAPSED: tuple[tuple[str, str], ...] = (
    ("instruction-override", r"(ignore|disregard)(all|any|the)?(previous|prior|above|earlier)"),
    (
        "mark-instruction",
        r"(give|award|assign|grant)(me|this|it|my)+(answer)?(the)?(full|top|maximum|highest)marks?",
    ),
    ("mark-instruction", r"(give|award|assign|grant)(me)?(full|maximum)marks?"),
    ("fence-imitation", r"(begin|end)studenttypedanswer"),
)

_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _PATTERNS)
_COMPILED_COLLAPSED = tuple((name, re.compile(pattern)) for name, pattern in _COLLAPSED)


# Look-alike letters from other scripts, folded to the Latin they imitate.
# ponytail: ~25 common ones, not the full Unicode confusables table; add on demand.
_HOMOGLYPHS = str.maketrans(
    "аеорсухіјѕкмтнвԁѵοαειντρυκχ",
    "aeopcyxijskmthbdvoaeivtpukx",
)
# ة->ه and ى->ي so the usual spelling variants meet; tatweel is padding.
_ARABIC_FOLD = str.maketrans({"ة": "ه", "ى": "ي", "ـ": None})


def _normalise(text: str) -> str:
    """Fold look-alike forms and drop what a reader does not see.

    NFKC then NFKD splits letters from their marks; Cf (zero-width), Mn
    (accents, Arabic harakat and hamza) and Cc (control) characters are dropped
    except real whitespace. That breaks no word for a model but defeats every
    regex that expected the letters to be adjacent."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
    kept = (c for c in text if c.isspace() or unicodedata.category(c) not in ("Cf", "Mn", "Cc"))
    return "".join(kept).casefold().translate(_HOMOGLYPHS).translate(_ARABIC_FOLD)


@dataclass(frozen=True)
class ScanResult:
    """Whether the text addressed the marker, and which rule said so."""

    flagged: bool
    reason: str | None = None


def scan_typed_answer(text: str | None) -> ScanResult:
    """Look for text addressing the marker rather than answering the question.

    Returns on the first hit: the tutor needs to know *that* it happened and
    roughly what fired, not an exhaustive catalogue of every match.
    """
    if not text:
        return ScanResult(flagged=False)
    text = _normalise(text)
    collapsed = re.sub(r"[\W_]+", "", text)
    for name, pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            # The matched fragment, bounded. A tutor deciding whether this was
            # an attempt or a turn of phrase needs to see the words; the whole
            # answer is already in front of them, so this is a pointer into it.
            excerpt = match.group(0)[:120]
            return ScanResult(flagged=True, reason=f"{name}: {excerpt!r}")
    for name, pattern in _COMPILED_COLLAPSED:
        match = pattern.search(collapsed)
        if match:
            return ScanResult(flagged=True, reason=f"{name}: {match.group(0)[:120]!r}")
    return ScanResult(flagged=False)
