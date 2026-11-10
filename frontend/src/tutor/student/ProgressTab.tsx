import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { topicEvidence, type ReadinessSummary } from "../../api/readiness";
import { studentMistakes, type MistakeTally } from "../../api/students";
import { SubjectReadinessCard } from "../../components/ReadinessView";
import CustomCriteriaPanel from "../../components/CustomCriteriaPanel";
import AttendancePanel from "../../components/AttendancePanel";
import { ABSENT, sourceLabel } from "../../lib/labels";
import { EmptyState, SectionCard } from "../../components/ui";
import { Button } from "../../components/controls";
import { SectionSkeleton } from "../../components/page";

export default function ProgressTab({
  studentId: sid,
  readiness: r,
  selectedTopic,
  setSelectedTopic,
}: {
  studentId: number;
  readiness: ReadinessSummary;
  selectedTopic: number | null;
  setSelectedTopic: (id: number | null) => void;
}) {
  const evidence = useQuery({
    queryKey: ["topic-evidence", sid, selectedTopic],
    queryFn: () => topicEvidence(sid, selectedTopic!),
    enabled: selectedTopic !== null,
  });

  return (
    <div className="space-y-6">
      {r.subjects.map((s) => (
        <SubjectReadinessCard key={s.subject_id} subject={s} onTopicClick={setSelectedTopic} />
      ))}
      {r.subjects.length === 0 && (
        <SectionCard>
          <EmptyState
            title="No readiness yet"
            hint="Readiness appears once this student's work is marked."
          />
        </SectionCard>
      )}

      {/* Right under the readiness it explains, so a click on a topic opens
          its evidence where the tutor is looking. */}
      {selectedTopic !== null && (
        <SectionCard>
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg text-ink-900">
              {evidence.data ? (
                <>
                  Evidence for {evidence.data.topic_title}
                  <span className="ml-2 font-sans text-sm text-ink-500">
                    {evidence.data.topic_code}
                  </span>
                </>
              ) : (
                "Evidence"
              )}
            </h2>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Close evidence"
              onClick={() => setSelectedTopic(null)}
            >
              <X aria-hidden className="h-4 w-4" />
              Close
            </Button>
          </div>
          {evidence.isLoading ? (
            <div className="mt-3">
              <SectionSkeleton rows={3} label="Loading evidence" />
            </div>
          ) : evidence.isError || !evidence.data ? (
            // A retry here rather than "refresh the page", which would also
            // close this panel and drop the topic the tutor had opened.
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <p role="alert" className="text-sm text-ink-500">
                {ABSENT.loadFailedRetry}
              </p>
              <Button
                variant="secondary"
                size="sm"
                loading={evidence.isFetching}
                onClick={() => evidence.refetch()}
              >
                Try again
              </Button>
            </div>
          ) : (
            <>
              <p className="mt-1 text-sm text-ink-500">
                {evidence.data.score !== null ? (
                  <>
                    Readiness {Math.round(evidence.data.score)}% ({evidence.data.confidence}{" "}
                    confidence)
                    {evidence.data.tutor_estimate && (
                      <span className="ml-1 text-xs text-ink-500">includes tutor estimate</span>
                    )}{" "}
                    —{" "}
                  </>
                ) : (
                  "Not enough data yet — "
                )}
                every score is explainable by the evidence below.
              </p>
              <ul className="mt-3 divide-y divide-line text-sm">
                {evidence.data.evidence.map((e, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 py-2">
                    <span className="min-w-0 text-ink-700">
                      {e.label ?? sourceLabel(e.source_type)}{" "}
                      <span className="text-xs text-ink-500">({sourceLabel(e.source_type)})</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-3 tabular-nums">
                      <span className="text-ink-900">{Math.round(e.score_pct)}%</span>
                      <span className="text-xs text-ink-500">
                        {new Date(e.occurred_at).toLocaleDateString()}
                      </span>
                    </span>
                  </li>
                ))}
                {evidence.data.evidence.length === 0 && (
                  <li className="py-2 text-ink-500">No evidence yet.</li>
                )}
              </ul>
            </>
          )}
        </SectionCard>
      )}

      {/* Beside readiness, never in it (owner decision 6). */}
      <CustomCriteriaPanel studentId={sid} editable />

      {/* Beside readiness, never in it (AV-33). */}
      <AttendancePanel studentId={sid} />

      {/* One per subject, each named: a single section fed by one subject would
          silently omit every other subject the student takes (PROD-2). */}
      {r.subjects.map((s) => (
        <MistakeRollupSection
          key={s.subject_id}
          studentId={sid}
          subjectId={s.subject_id}
          subjectName={s.subject_name}
        />
      ))}
    </div>
  );
}

/* The mistake rollup (4.4).

   Two failures this section exists to not commit. First, a student nobody has
   examined must never read as flawless: `analysed_questions === 0` is absence
   and is rendered as absence, never as "0 mistakes" and never as an empty
   table (PROD-2, UX-19) — which is also why a failed request gets its own
   wording rather than falling through to the clean-record line. Second, the
   per-topic and per-chapter numbers must never be added up: a mistake on a
   question testing three topics is counted under each of the three on purpose
   (decision 11), so every bucket is labelled "touching" and `total` is the
   only subject figure. Category names are the tutor's own words — rendered,
   never branched on, because they can be renamed tomorrow. */
const countMistakes = (n: number) => `${n} mistake${n === 1 ? "" : "s"}`;

function CategoryChips({ categories }: { categories: MistakeTally["categories"] }) {
  return (
    <>
      {categories.map((c) => (
        <span
          key={c.category_id}
          className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-ink-700"
        >
          {c.category_name} {c.mistakes} · severity {c.severity_total}
        </span>
      ))}
    </>
  );
}

function TallyDetail({ tally }: { tally: MistakeTally }) {
  return (
    <span className="flex flex-wrap items-baseline gap-2 text-sm text-ink-500">
      <span>{countMistakes(tally.mistakes)}</span>
      <span className="text-xs">severity {tally.severity_total}</span>
      <CategoryChips categories={tally.categories} />
    </span>
  );
}

function TallyList({
  title,
  note,
  rows,
}: {
  title: string;
  note: string;
  rows: { key: string; label: string; tally: MistakeTally }[];
}) {
  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-ink-900">{title}</h3>
      <p className="mt-0.5 text-xs text-ink-500">{note}</p>
      <ul className="mt-2 divide-y divide-line">
        {rows.map((r) => (
          <li
            key={r.key}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2"
          >
            <span className="text-sm text-ink-700">{r.label}</span>
            <TallyDetail tally={r.tally} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function MistakeRollupSection({
  studentId,
  subjectId,
  subjectName,
}: {
  studentId: number;
  subjectId: number;
  subjectName: string;
}) {
  const rollup = useQuery({
    queryKey: ["student-mistakes", studentId, subjectId],
    queryFn: () => studentMistakes(studentId, subjectId),
  });

  const d = rollup.data;
  return (
    <SectionCard>
      <h2 className="text-lg text-ink-900">Mistakes in {subjectName}</h2>
      {rollup.isPending ? (
        <div className="mt-3">
          <SectionSkeleton rows={2} label={`Loading mistakes in ${subjectName}`} />
        </div>
      ) : rollup.isError || !d ? (
        // Never the clean-record line and never an empty table: a request that
        // failed knows nothing about this student's work (PROD-2).
        <p role="alert" className="mt-1 text-sm text-risk-600">
          Could not load mistakes. {ABSENT.loadFailed}
        </p>
      ) : d.analysed_questions === 0 ? (
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          Nobody has examined this student's work for mistakes — {ABSENT.noEvidence}. An empty
          record here is not a clean one.
        </p>
      ) : d.total.mistakes === 0 ? (
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          No mistakes recorded in the {d.analysed_questions} questions examined so far.
        </p>
      ) : (
        <>
          <p className="mt-1 flex flex-wrap items-baseline gap-2 text-sm text-ink-700">
            <span>
              {countMistakes(d.total.mistakes)} across {d.analysed_questions} examined questions
            </span>
            <span className="text-xs text-ink-500">severity {d.total.severity_total}</span>
            <CategoryChips categories={d.total.categories} />
          </p>
          <TallyList
            title="By topic"
            note={`Mistakes touching each topic. One mistake on a question that tests several topics is counted under each of them, so these do not add up to ${d.total.mistakes}.`}
            rows={[
              ...d.topics.map((t) => ({
                key: `topic-${t.topic_id}`,
                label: t.topic_title,
                tally: t.tally,
              })),
              {
                key: "topicless",
                label: "Not linked to any topic",
                tally: d.topicless,
              },
            ]}
          />
          <TallyList
            title="By chapter"
            note="Mistakes touching each chapter, on the same counting — a mistake spanning two chapters is in both."
            rows={[
              ...d.chapters.map((c) => ({
                key: `chapter-${c.chapter_id}`,
                label: c.chapter_title,
                tally: c.tally,
              })),
              {
                key: "chapterless",
                label: "Topics with no chapter",
                tally: d.chapterless,
              },
            ]}
          />
        </>
      )}
    </SectionCard>
  );
}
