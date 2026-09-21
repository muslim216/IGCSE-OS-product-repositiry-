"""The tutor-facing shape of a student's mistakes across one subject (4.4).

Every number here is a count of rows that exist, never a rate and never a
score (`PROD-1`). The severity sums are the same integers the tutor sees on
each mistake, added up — not normalised, not scaled.
"""

from pydantic import BaseModel


class CategoryTally(BaseModel):
    """How often one of the tutor's own categories came up in a bucket.

    Named by id *and* name: the id is what a client filters or links on, the
    name is what the tutor reads and may rename tomorrow. Nothing branches on
    the name (see `models.readiness_v2.MistakeCategory`).
    """

    category_id: int
    category_name: str
    mistakes: int
    #: Severities added, not averaged. Three careless slips and one major
    #: misconception both read as "4" on a mean; the sum says which body of
    #: work is heavier, and the count beside it says how it got there.
    severity_total: int


class MistakeTally(BaseModel):
    """One bucket's totals: how many mistakes, how heavy, and of what kinds."""

    mistakes: int
    severity_total: int
    categories: list[CategoryTally]


class TopicMistakes(BaseModel):
    """Mistakes **touching** this topic — not mistakes "in" it.

    A question tests several topics, so one mistake is counted under each of
    them (decision 11). Label it as touching the topic wherever it is shown;
    "mistakes in this topic" invites a reader to add the rows up, and that
    over-counts. `StudentMistakeRollup.total` is the only subject figure.
    """

    topic_id: int
    topic_title: str
    #: The chapter this topic sits under, or null for a flat pre-2.3 topic.
    #: Those mistakes are in `StudentMistakeRollup.chapterless`, not under any
    #: chapter — carried here so a client can say which topics put them there.
    chapter_id: int | None
    tally: MistakeTally


class ChapterMistakes(BaseModel):
    """Mistakes touching any topic of this chapter, counted once per chapter.

    A mistake on a question spanning two topics of the same chapter is one
    mistake here, and a mistake spanning two chapters counts in both.
    """

    chapter_id: int
    chapter_title: str
    tally: MistakeTally


class StudentMistakeRollup(BaseModel):
    """One student, one subject, all time."""

    student_id: int
    subject_id: int
    #: The denominator. Questions on settled submissions the tagging job has
    #: actually examined. **Zero means no data, not a clean record** — a
    #: student nobody has examined has no mistakes for the same reason an
    #: unopened book has no mistakes (`PROD-2`, `UX-19`).
    analysed_questions: int
    #: The subject figure, and the only one. Computed from distinct mistakes,
    #: so it is *not* the sum of `topics[].tally.mistakes` — that sum counts a
    #: multi-topic mistake once per topic, on purpose. A client needing "how
    #: many mistakes in this subject" reads this field and never adds.
    total: MistakeTally
    topics: list[TopicMistakes]
    #: Mistakes on a bare question — one whose extraction found no topics, so
    #: the mistake has no `mistake_topics` rows (decision 15). They are in
    #: `total` and they are here, and they are in no topic and no chapter.
    #: Shown as its own named group, never folded into a chapter and never
    #: dropped: dropping them is what makes the per-topic rows stop
    #: reconciling with the readiness factor's subject count (`RISK-5`).
    topicless: MistakeTally
    chapters: list[ChapterMistakes]
    #: Mistakes whose topics have no chapter — `topics.chapter_id` is nullable
    #: until syllabus extraction is chapter-first (task 2.3). Same treatment
    #: and the same reason as `topicless`.
    chapterless: MistakeTally


class MyCategoryCount(BaseModel):
    """How many mistakes of one kind the student themselves has made.

    Deliberately not `CategoryTally`: no `severity_total`, at any nesting
    level. Severity is an internal weighting signal, and to the person who made
    the mistakes it reads as a verdict on them rather than as a number the
    engine uses. A field that exists is a field that leaks, so the student's
    response cannot carry one for a client to remember not to render (4.5).
    """

    category_id: int
    category_name: str
    mistakes: int


class MyMistakePattern(BaseModel):
    """One subject's mistakes as the student who made them sees them (4.5).

    Categories only, and no severity. The per-topic and per-chapter breakdown
    the tutor gets is also left out on purpose — a student is shown *what
    kinds* of mistakes they make, not a map of where in the syllabus they fall.
    """

    subject_id: int
    subject_name: str
    #: The denominator, exactly as in `StudentMistakeRollup`. **Zero means
    #: nobody has examined this subject's work yet, not a clean record**, and
    #: the two must stay distinguishable on screen (`PROD-2`, `UX-19`).
    analysed_questions: int
    #: Distinct mistakes in this subject — `StudentMistakeRollup.total.mistakes`
    #: projected down. The same figure the tutor sees, from the same query.
    total_mistakes: int
    categories: list[MyCategoryCount]
