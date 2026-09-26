import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  createObservation,
  listObservations,
  seedStudentReadiness,
  studentReadiness,
  topicEvidence,
  type Observation,
} from "../api/readiness";
import { listTopics } from "../api/syllabus";
import { studentMistakes, type MistakeTally } from "../api/students";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";
import { ABSENT, sourceLabel } from "../lib/labels";

export default function StudentDetailPage() {
  const { studentId } = useParams();
  const sid = Number(studentId);
  const [params] = useSearchParams();
  const groupId = params.get("group");
  const subjectIdParam = params.get("subject");
  const queryClient = useQueryClient();

  const readiness = useQuery({
    queryKey: ["student-readiness", sid],
    queryFn: () => studentReadiness(sid),
  });
  const [selectedTopic, setSelectedTopic] = useState<number | null>(null);

  const evidence = useQuery({
    queryKey: ["topic-evidence", sid, selectedTopic],
    queryFn: () => topicEvidence(sid, selectedTopic!),
    enabled: selectedTopic !== null,
  });

  const subjectId = subjectIdParam
    ? Number(subjectIdParam)
    : readiness.data?.subjects[0]?.subject_id;
  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId!),
    enabled: subjectId !== undefined,
  });

  const observations = useQuery({
    queryKey: ["observations", sid],
    queryFn: () => listObservations(sid),
  });
  const [obs, setObs] = useState({ topic_id: "", comment: "", rating: "" });
  const addObservation = useMutation({
    mutationFn: () =>
      createObservation({
        student_id: sid,
        topic_id: obs.topic_id ? Number(obs.topic_id) : null,
        comment: obs.comment,
        rating: obs.rating ? Number(obs.rating) : null,
      }),
    onSuccess: () => {
      setObs({ topic_id: "", comment: "", rating: "" });
      // An observation changes the profile's list, never readiness (PROD-15).
      queryClient.invalidateQueries({ queryKey: ["observations", sid] });
    },
  });

  function onObserve(e: FormEvent) {
    e.preventDefault();
    if (obs.comment) addObservation.mutate();
  }

  const [seed, setSeed] = useState({ topic_id: "", score_pct: "" });
  const seedReadiness = useMutation({
    mutationFn: () =>
      seedStudentReadiness(sid, [
        { topic_id: Number(seed.topic_id), score_pct: Number(seed.score_pct) },
      ]),
    onSuccess: () => {
      setSeed({ topic_id: "", score_pct: "" });
      queryClient.invalidateQueries({ queryKey: ["student-readiness", sid] });
    },
  });

  function onSeed(e: FormEvent) {
    e.preventDefault();
    if (seed.topic_id && seed.score_pct !== "") seedReadiness.mutate();
  }

  if (readiness.isLoading) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      {groupId && (
        <Link to={`/tutor/groups/${groupId}`} className="text-sm text-blue-600 hover:underline">
          ← Back to group
        </Link>
      )}
      <h2 className="text-xl font-semibold text-slate-800">{readiness.data?.student_name}</h2>

      <div className="grid gap-4 lg:grid-cols-2">
        {readiness.data?.subjects.map((s) => (
          <SubjectReadinessCard key={s.subject_id} subject={s} onTopicClick={setSelectedTopic} />
        ))}
        {readiness.data?.subjects.length === 0 && (
          <p className="text-slate-500">No readiness data yet for this student.</p>
        )}
      </div>

      {/* One per subject, each named. A single section fed by the page's
          `subjectId` showed the first subject's mistakes under a bare
          "Mistakes" heading and silently omitted every other subject the
          student takes — a tutor reading it would have no way to tell (cubic,
          PROD-2 applied to a whole subject rather than a number). */}
      {readiness.data?.subjects.map((s) => (
        <MistakeRollupSection
          key={s.subject_id}
          studentId={sid}
          subjectId={s.subject_id}
          subjectName={s.subject_name}
        />
      ))}

      {selectedTopic !== null && evidence.data && (
        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">
              Evidence for {evidence.data.topic_code} {evidence.data.topic_title}
            </h3>
            <button
              onClick={() => setSelectedTopic(null)}
              className="text-sm text-slate-400 hover:text-slate-700"
            >
              Close
            </button>
          </div>
          <p className="mt-1 text-sm text-ink-500">
            {evidence.data.score !== null ? (
              <>
                Readiness {Math.round(evidence.data.score)}% ({evidence.data.confidence} confidence)
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
          <ul className="mt-2 divide-y divide-line text-sm">
            {evidence.data.evidence.map((e, i) => (
              <li key={i} className="flex items-center justify-between py-1.5">
                <span className="text-ink-700">
                  {e.label ?? sourceLabel(e.source_type)}{" "}
                  <span className="text-xs text-ink-500">({sourceLabel(e.source_type)})</span>
                </span>
                <span className="flex items-center gap-3 text-ink-500">
                  <span>{Math.round(e.score_pct)}%</span>
                  <span className="text-xs text-ink-500">
                    {new Date(e.occurred_at).toLocaleDateString()}
                  </span>
                </span>
              </li>
            ))}
            {evidence.data.evidence.length === 0 && (
              <li className="py-1.5 text-ink-500">No evidence yet.</li>
            )}
          </ul>
        </div>
      )}

      <ReportsPanel studentId={sid} audiences={["student", "tutor", "parent"]} />

      {/* Seeding (spec §7.3). Optional, and deliberately late: students attach
          themselves by invite code, so a tutor finishing setup has no students
          to rate. It exists so a class that has just filled shows something on
          day one instead of "not enough data yet" everywhere for three weeks —
          and it is labelled self-declared wherever it lands (PROD-8), and gives
          way as marked work arrives, so a first impression corrects itself. */}
      <div className="rounded-lg border border-line bg-surface p-4">
        <h3 className="font-medium text-ink-900">Starting estimate</h3>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          Where you think this student stands, before their work has been marked. Recorded as
          self-declared, and it loses weight as real marked work arrives.
        </p>
        <form onSubmit={onSeed} className="mt-3 flex flex-wrap items-center gap-2">
          <select
            aria-label="Topic to estimate"
            className="rounded border border-line-control px-3 py-2 text-sm"
            value={seed.topic_id}
            onChange={(e) => setSeed({ ...seed, topic_id: e.target.value })}
            required
          >
            <option value="">Choose a topic</option>
            {topics.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.code} {t.title}
              </option>
            ))}
          </select>
          {topics.data?.length === 0 && (
            // The select is empty when the student has no subject yet — say so,
            // rather than leaving a control that cannot be completed (CodeRabbit).
            <p className="w-full text-sm text-ink-500">
              No topics to estimate yet — they appear once this student has a subject.
            </p>
          )}
          <input
            type="number"
            min={0}
            max={100}
            aria-label="Estimated percentage"
            placeholder="0–100"
            className="w-28 rounded border border-line-control px-3 py-2 text-sm"
            value={seed.score_pct}
            onChange={(e) => setSeed({ ...seed, score_pct: e.target.value })}
            required
          />
          <button
            type="submit"
            disabled={seedReadiness.isPending}
            className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
          >
            Save estimate
          </button>
          {/* A live region so assistive technology announces the outcome — the
              form otherwise signals success only by resetting its fields, which
              a screen reader does not surface (CodeRabbit). */}
          <p className="w-full text-sm" aria-live="polite">
            {seedReadiness.isError ? (
              <span className="text-risk-600">Could not save the estimate.</span>
            ) : seedReadiness.isSuccess ? (
              <span className="text-ink-500">Estimate saved.</span>
            ) : null}
          </p>
        </form>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Add an observation</h3>
        <p className="mt-1 text-sm text-slate-500">
          Observations stay on this profile as your professional judgement. They never change a
          readiness score.
        </p>
        <form onSubmit={onObserve} className="mt-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            <select
              className="rounded border border-slate-300 px-3 py-2 text-sm"
              value={obs.topic_id}
              onChange={(e) => setObs({ ...obs, topic_id: e.target.value })}
            >
              <option value="">General (no topic)</option>
              {topics.data?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.code} {t.title}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={0}
              max={100}
              placeholder="Rating 0–100"
              className="w-32 rounded border border-slate-300 px-3 py-2 text-sm"
              value={obs.rating}
              onChange={(e) => setObs({ ...obs, rating: e.target.value })}
            />
          </div>
          <textarea
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            rows={2}
            placeholder="What did you notice?"
            value={obs.comment}
            onChange={(e) => setObs({ ...obs, comment: e.target.value })}
            required
          />
          <button
            type="submit"
            disabled={addObservation.isPending}
            className="rounded-md bg-slate-700 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save observation
          </button>
          {addObservation.isError && (
            <p className="text-sm text-red-600">Could not save the observation.</p>
          )}
        </form>
        <ObservationList
          observations={observations}
          topicName={(id) => {
            const t = topics.data?.find((x) => x.id === id);
            return t ? `${t.code} ${t.title}` : null;
          }}
        />
      </div>
    </div>
  );
}

/* Saved observations. This list is the only place an observation is shown:
   since PROD-15 it is a profile note and never appears as readiness evidence,
   so without it a tutor's note would be written and never seen again. A
   failed load gets its own line, never the empty-state wording (UX-19). */
function ObservationList({
  observations,
  topicName,
}: {
  observations: UseQueryResult<Observation[]>;
  topicName: (topicId: number) => string | null;
}) {
  return (
    <section aria-labelledby="saved-observations" className="mt-4 border-t border-line pt-3">
      <h4 id="saved-observations" className="text-sm font-medium text-ink-700">
        Saved observations
      </h4>
      <ObservationRows observations={observations} topicName={topicName} />
    </section>
  );
}

function ObservationRows({
  observations,
  topicName,
}: {
  observations: UseQueryResult<Observation[]>;
  topicName: (topicId: number) => string | null;
}) {
  if (observations.isLoading) return <p className="mt-2 text-sm text-ink-500">Loading…</p>;
  if (observations.isError)
    return <p className="mt-2 text-sm text-risk-600">Could not load observations.</p>;
  const rows = observations.data ?? [];
  if (rows.length === 0) return <p className="mt-2 text-sm text-ink-500">No observations yet.</p>;
  return (
    <ul className="mt-2 divide-y divide-line">
      {rows.map((o) => (
        <li key={o.id} className="py-2 text-sm">
          <p className="text-ink-500">
            {new Date(o.created_at).toLocaleDateString()}
            {" · "}
            {o.topic_id === null
              ? "General"
              : // Topics load for the subject in view; a note on another
                // subject's topic still names which one, never a bare "Topic".
                (topicName(o.topic_id) ?? `Topic #${o.topic_id}`)}
            {o.rating !== null && ` · Rating ${o.rating}/100`}
          </p>
          <p className="mt-0.5 whitespace-pre-line text-ink-900">{o.comment}</p>
        </li>
      ))}
    </ul>
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
      <h4 className="text-sm font-medium text-ink-700">{title}</h4>
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
    <section className="mt-4 rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Mistakes in {subjectName}</h3>
      {rollup.isPending ? (
        <p className="mt-1 text-sm text-ink-500">Loading…</p>
      ) : rollup.isError || !d ? (
        // Never the clean-record line and never an empty table: a request that
        // failed knows nothing about this student's work (PROD-2).
        <p className="mt-1 text-sm text-risk-600">Could not load mistakes. {ABSENT.loadFailed}</p>
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
    </section>
  );
}
