"""Wires every job type to its handler.

Lifted out of `main.py` by task 1.3 (AV-82). The registrations were only ever
reachable by importing the API, which is fine while the worker runs inside it
and impossible once it does not: a standalone worker importing `app.main` would
be the worker layer reaching up into the routing layer, which `BE-1` forbids and
which would drag the entire FastAPI app into a process that serves no HTTP.

Importing this module is what makes a worker able to do anything, so both
entry points import it: `app.main` for the in-process worker, and
`app.workers.__main__` for the standalone one. It imports only from `services/`,
which is the direction `BE-1` allows.
"""

from app.services.extraction import extract_assignment, extract_past_paper
from app.services.google_classroom import sync_classroom
from app.services.marking import mark_submission
from app.services.narrative import (
    CLASS_NARRATIVE_JOB,
    SWEEP_JOB,
    generate_narrative,
    sweep_parent_narratives,
)
from app.services.readiness import recompute_student
from app.services.readiness_v2_ai import compute_readiness_v2
from app.services.reports import generate_report
from app.services.syllabus_extraction import extract_syllabus
from app.workers.jobs import register_handler


def register_all() -> None:
    """Register every job handler. Idempotent — registration is a dict
    assignment keyed by job type, so importing twice cannot double-register."""
    register_handler("extract_assignment", extract_assignment)
    # A past paper is a full-paper classified: same extractor, same prompt.
    register_handler("extract_past_paper", extract_past_paper)
    register_handler("mark_submission", mark_submission)
    register_handler("recompute_readiness", recompute_student)
    # Readiness v2 is what the readiness UI/API serve
    # (services/readiness_summary_v2.py), falling back to v1 for any
    # (student, subject) with no snapshot yet. Runs are enqueued debounced per
    # (student, subject) so a burst of auto-finalized submissions costs one
    # synthesis, not one each.
    register_handler("compute_readiness_v2", compute_readiness_v2)
    register_handler("generate_report", generate_report)
    register_handler("extract_syllabus", extract_syllabus)
    # Polling sync: imports courseWork/submissions from every course a tutor has
    # linked. Its router is unmounted (0.5, AV-58) so nothing enqueues this
    # today, but the handler stays registered: rows of type "sync_classroom" may
    # still sit in the jobs table from before the surface was hidden, and an
    # unregistered type fails them permanently rather than draining. Re-mounting
    # the router in api/classroom.py is all it takes to bring the surface back.
    register_handler("sync_classroom", sync_classroom)
    # The stored narrative (services/narrative.py). The class paragraph is
    # enqueued from the tail of the evidence build; the parent paragraph by a
    # weekly sweep that re-derives who is due and re-enqueues itself — never a
    # self-perpetuating per-student chain, whose schedule would die with one
    # failed job row.
    register_handler(CLASS_NARRATIVE_JOB, generate_narrative)
    register_handler(SWEEP_JOB, sweep_parent_narratives)
