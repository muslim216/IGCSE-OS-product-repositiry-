"""Where one student's tagged mistakes fall across a subject's syllabus (4.4).

Read time, no table and no job (decision Q9): the rows already exist, and a
stored rollup is a second copy that goes stale the moment a tutor revises a tag.

All time, no window and no decay. A mistake a student made in October is still
something they did; the readiness factor is where recency is weighed, not here.

**The scoping here is a mirror of `readiness_v2._mistake_points_and_analysed`
and must stay one.** That function decides which mistakes the Mistake Analysis
readiness factor counts; this one decides which mistakes a tutor is shown. Two
answers to "which mistakes count" is the `RISK-5` failure — a screen and a score
disagreeing, with nothing raising a word about it. If one of the two gains a
condition, the other gains it in the same change.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SETTLED_STATUSES,
    AssessableWork,
    Chapter,
    Mistake,
    MistakeCategory,
    MistakeTopic,
    QuestionMark,
    Submission,
    Topic,
)
from app.schemas.mistake_rollup import (
    CategoryTally,
    ChapterMistakes,
    MistakeTally,
    StudentMistakeRollup,
    TopicMistakes,
)


@dataclass
class _Tally:
    """One bucket, accumulated by mistake id rather than by row.

    A set, not a counter, because the query fans out: a mistake on a
    three-topic question comes back as three rows, and two of those topics may
    sit in the same chapter. Counting rows would report that chapter three
    mistakes where the student made one. De-duplication is per bucket, so the
    same mistake still counts in every *different* topic and chapter it
    touches — that is decision 11, and it is why these numbers must never be
    summed (see `StudentMistakeRollup.total_mistakes`).
    """

    mistake_ids: set[int] = field(default_factory=set)
    severity: int = 0
    by_category: dict[int, tuple[str, set[int], int]] = field(default_factory=dict)

    def add(self, mistake_id: int, severity: int, category_id: int, category_name: str) -> None:
        if mistake_id in self.mistake_ids:
            return
        self.mistake_ids.add(mistake_id)
        self.severity += severity
        _, ids, total = self.by_category.setdefault(category_id, (category_name, set(), 0))
        ids.add(mistake_id)
        self.by_category[category_id] = (category_name, ids, total + severity)

    def out(self) -> MistakeTally:
        return MistakeTally(
            mistakes=len(self.mistake_ids),
            severity_total=self.severity,
            categories=sorted(
                (
                    CategoryTally(
                        category_id=category_id,
                        category_name=name,
                        mistakes=len(ids),
                        severity_total=severity,
                    )
                    for category_id, (name, ids, severity) in self.by_category.items()
                ),
                key=lambda c: (-c.mistakes, c.category_name),
            ),
        )


async def roll_up_mistakes(
    session: AsyncSession, *, student_id: int, subject_id: int
) -> StudentMistakeRollup:
    """Every tagged mistake this student has made in this subject, grouped by
    topic and by chapter, with the two buckets nothing in the syllabus claims.

    No HTTP concerns here (`BE-2`): the caller has already proved the tutor may
    see this student and owns this subject.
    """
    # The denominator, gated identically to the mistake query below. Zero
    # analysed questions means nothing has been examined, which is *not* a
    # clean record — the caller shows "not enough data yet", never "0 mistakes"
    # (`PROD-2`, `UX-19`). Counted here rather than imported from
    # readiness_v2 so this module does no work in the readiness engine's
    # request-free path; the gate is the thing that must match, not the call.
    analysed_questions = (
        await session.scalar(
            select(func.count(QuestionMark.id))
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .where(
                Submission.student_id == student_id,
                AssessableWork.subject_id == subject_id,
                Submission.status.in_(SETTLED_STATUSES),
                Submission.mistakes_analysed_at.is_not(None),
            )
        )
    ) or 0

    # Outer joins from `Mistake` outward, deliberately. An inner join to `Topic`
    # drops every mistake on a bare question — one whose extraction found no
    # topics, which `mistake_tagging` writes with no `MistakeTopic` rows at all
    # (decision 15) — and an inner join to `Chapter` drops every pre-2.3 flat
    # topic, whose `chapter_id` is still NULL. Both are real states today, and
    # both disappear without an error, a log line or a number that looks wrong.
    # They get named buckets below instead (`PROD-2`).
    #
    # `Mistake.source` is deliberately not filtered: a tutor-revised mistake
    # counts exactly as an AI-tagged one. The reasoning is written out in
    # `readiness_v2._mistake_points_and_analysed`; do not "fix" the absence.
    rows = (
        await session.execute(
            select(
                Mistake.id,
                Mistake.severity,
                MistakeCategory.id,
                MistakeCategory.name,
                Topic.id,
                Topic.title,
                Chapter.id,
                Chapter.title,
            )
            .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .join(MistakeCategory, MistakeCategory.id == Mistake.category_id)
            .outerjoin(MistakeTopic, MistakeTopic.mistake_id == Mistake.id)
            .outerjoin(Topic, Topic.id == MistakeTopic.topic_id)
            .outerjoin(Chapter, Chapter.id == Topic.chapter_id)
            .where(
                Mistake.student_id == student_id,
                AssessableWork.subject_id == subject_id,
                Submission.status.in_(SETTLED_STATUSES),
                Submission.mistakes_analysed_at.is_not(None),
            )
        )
    ).all()

    by_topic: dict[int, tuple[str, int | None, _Tally]] = {}
    by_chapter: dict[int, tuple[str, _Tally]] = {}
    no_topic = _Tally()
    no_chapter = _Tally()
    subject_total = _Tally()

    for mistake_id, severity, category_id, category_name, t_id, t_title, c_id, c_title in rows:
        subject_total.add(mistake_id, severity, category_id, category_name)
        if t_id is None:
            no_topic.add(mistake_id, severity, category_id, category_name)
            continue
        _, _, topic_tally = by_topic.setdefault(t_id, (t_title, c_id, _Tally()))
        topic_tally.add(mistake_id, severity, category_id, category_name)
        if c_id is None:
            no_chapter.add(mistake_id, severity, category_id, category_name)
            continue
        _, chapter_tally = by_chapter.setdefault(c_id, (c_title, _Tally()))
        chapter_tally.add(mistake_id, severity, category_id, category_name)

    return StudentMistakeRollup(
        student_id=student_id,
        subject_id=subject_id,
        analysed_questions=analysed_questions,
        total=subject_total.out(),
        topics=sorted(
            (
                TopicMistakes(
                    topic_id=topic_id, topic_title=title, chapter_id=chapter_id, tally=tally.out()
                )
                for topic_id, (title, chapter_id, tally) in by_topic.items()
            ),
            key=lambda t: (-t.tally.mistakes, t.topic_id),
        ),
        topicless=no_topic.out(),
        chapters=sorted(
            (
                ChapterMistakes(chapter_id=chapter_id, chapter_title=title, tally=tally.out())
                for chapter_id, (title, tally) in by_chapter.items()
            ),
            key=lambda c: (-c.tally.mistakes, c.chapter_id),
        ),
        chapterless=no_chapter.out(),
    )
