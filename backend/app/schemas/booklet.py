"""Wire contracts for booklets — one upload holding several whole past papers.

The draft is the AI's reading of what is inside the document, and the tutor has
final authority over it (`PROD-7`): they can correct every field, add a paper
the AI missed, and delete one it invented, before any of it becomes real.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class DraftPaper(BaseModel):
    """One paper the AI found inside a booklet, as the tutor may edit it."""

    title: str = Field(min_length=1, max_length=255)
    session_label: str = Field(min_length=1, max_length=64)
    paper_number: str = Field(min_length=1, max_length=32)
    # 1-based and inclusive, because that is what a page range read off a
    # booklet means to a tutor. `services/pdf.extract_pages` takes the same.
    first_page: int = Field(ge=1)
    last_page: int = Field(ge=1)

    @model_validator(mode="after")
    def _range_runs_forwards(self) -> "DraftPaper":
        if self.last_page < self.first_page:
            raise ValueError(f"Pages {self.first_page}-{self.last_page} end before they start.")
        return self


class BookletDraft(BaseModel):
    """The full reviewed list. A tutor PUTs this back, corrected.

    `scheme_papers` and `scheme_mismatch` are read-only in practice — they come
    from the AI's second pass over the mark scheme — but they ride along on the
    round trip so an edit does not silently drop them.
    """

    papers: list[DraftPaper] = Field(min_length=1)
    scheme_papers: list[DraftPaper] | None = None
    scheme_mismatch: str | None = None

    @model_validator(mode="after")
    def _ranges_do_not_overlap(self) -> "BookletDraft":
        # Two papers claiming the same page means one of them is wrong, and
        # approving would cut those pages into two different papers — a student
        # would sit a paper holding half of someone else's.
        seen: list[tuple[int, int, str]] = []
        for paper in self.papers:
            for first, last, label in seen:
                if paper.first_page <= last and first <= paper.last_page:
                    raise ValueError(
                        f"'{paper.title}' (pages {paper.first_page}-{paper.last_page}) "
                        f"overlaps '{label}' (pages {first}-{last})."
                    )
            seen.append((paper.first_page, paper.last_page, paper.title))
        return self


class BookletOut(BaseModel):
    id: int
    subject_id: int
    # Null until the tutor names it; `display_title` is that with the fallback
    # applied. Both on the wire for the same reason `PastPaperOut` carries
    # both — a round-trip form must not write the fallback back (`PROD-2`).
    title: str | None
    display_title: str
    status: str
    file_name: str | None
    # Tutors only — a student must never learn whether a mark scheme exists,
    # let alone download it.
    mark_scheme_name: str | None = None
    error: str | None = None
    paper_count: int = 0
    created_at: datetime


class BookletDetail(BookletOut):
    draft: BookletDraft | None = None
