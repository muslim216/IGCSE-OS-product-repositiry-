"""Booklets: one uploaded document holding several whole past papers.

The word is now reserved for this and nothing else (0041 freed it). A booklet
is a *set of past papers* — the bound collection a tutor actually buys or
downloads. A classified is the other thing entirely: a set of questions for one
chapter, which lives in `models/syllabus.py`.

Every `PastPaper` belongs to exactly one booklet, including the common case of
a tutor uploading a single paper — that gets a booklet of one. One parent for
every paper is what lets the file, the mark scheme and the extraction status
live in a single place instead of being duplicated per paper, and it is why
`PastPaper.booklet_id` is NOT NULL.

The shape of the extract -> review -> apply flow is `SyllabusUpload`'s
(file + status + AI `draft` a tutor edits before it becomes real rows), because
it is the same flow: the AI reads the document, proposes a list, and nothing is
created until the tutor applies it.
"""

import enum

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BookletStatus(str, enum.Enum):
    extracting = "extracting"
    extraction_failed = "extraction_failed"
    review = "review"
    # Between the tutor approving the list and the papers existing. Cutting a
    # booklet into its papers is CPU-bound work that has to happen off the
    # request (`BE-13`, `PERF-1`), so there is a real window where the tutor has
    # approved and nothing is there yet — without a state for it the screen
    # would say "ready" over an empty list. A new member costs no migration
    # (`DB-5`, `DB-6`).
    applying = "applying"
    # The cut itself failed — distinct from `extraction_failed`, which is the
    # AI failing to read the list. They recover in opposite directions: a failed
    # read is fixed by reading again, a failed cut by cutting again, and
    # re-reading after a partial cut would overwrite the list the tutor approved
    # while the papers already cut keep their old indexes (`PROD-7`).
    split_failed = "split_failed"
    applied = "applied"


class Booklet(TimestampMixin, Base):
    """A document holding several past papers, and the papers it produced."""

    __tablename__ = "booklets"
    # Every listing is org-scoped (`SEC-7`, `PROD-4`) and the tutor's booklet
    # list is then narrowed to one subject; a composite serves both, since the
    # org-only query uses it as a prefix.
    __table_args__ = (Index("ix_booklets_org_subject", "organization_id", "subject_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    # Nullable only to match `PastPaper.tutor_id`, which is nullable for seed
    # rows that predate owners: the booklets backfilled for those papers have no
    # owner to copy. Every booklet created through the API has one.
    tutor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    # Read off the document by extraction, never typed by the tutor — so it is
    # absent until that runs. See `display_title` for what call sites render
    # (`PROD-2`).
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The uploaded document. Nullable for the same reason as `tutor_id`: the
    # backfilled booklets of file-less seed papers have no file to copy.
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # One scheme may cover every paper in the booklet, so it is held here rather
    # than per paper. Optional: it is what makes a mark eligible to auto-finalize
    # (`AI-11`, `ADR-0009`), not what makes marking possible.
    mark_scheme_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mark_scheme_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[BookletStatus] = mapped_column(
        Enum(BookletStatus, native_enum=False, length=20),
        default=BookletStatus.extracting,
        nullable=False,
    )
    # How many pages the document actually has, counted once when the AI reads
    # it. It is what lets approval refuse a page range that runs past the end
    # *before* anything is cut: without it a hallucinated "pages 1-40" of a
    # 20-page booklet is only caught inside the split job, which fails, and a
    # half-cut booklet cannot be edited. Null for a booklet whose read never
    # finished, and for the booklets-of-one backfilled by 0042 — the check is
    # skipped rather than guessed (`PROD-2`).
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The AI's proposed paper list, tutor-editable until approval turns it into
    # `PastPaper` rows. Shape is `schemas.booklet.BookletDraft`: `papers`, the
    # `scheme_papers` read off the mark scheme, and `scheme_mismatch` when the
    # two disagree.
    draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def display_title(self) -> str:
        """Mirrors `PastPaper.display_title`: absent is shown as absent, never
        fabricated into a guess (`PROD-2`)."""
        return self.title or "Untitled booklet"
