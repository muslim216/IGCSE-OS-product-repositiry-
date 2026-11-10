import { type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  createObservation,
  listObservations,
  seedStudentReadiness,
  type Observation,
} from "../../api/readiness";
import { listTopics } from "../../api/syllabus";
import { SectionCard } from "../../components/ui";
import { Button, Field, Input, Select, Textarea } from "../../components/controls";
import { SectionSkeleton } from "../../components/page";

export type ObsDraft = { topic_id: string; comment: string; rating: string };
export type SeedDraft = { topic_id: string; score_pct: string };

/** A card's title and the sentence under it, at the page's h2 level. */
function CardTitle({ title, description }: { title: string; description?: string }) {
  return (
    <div>
      <h2 className="text-lg text-ink-900">{title}</h2>
      {description && <p className="mt-1 max-w-prose text-sm text-ink-500">{description}</p>}
    </div>
  );
}

// The drafts live in the page, so text typed here survives a switch to another tab.
export default function NotesTab({
  studentId: sid,
  subjectId,
  obs,
  setObs,
  seed,
  setSeed,
}: {
  studentId: number;
  subjectId: number | undefined;
  obs: ObsDraft;
  setObs: (v: ObsDraft) => void;
  seed: SeedDraft;
  setSeed: (v: SeedDraft) => void;
}) {
  const queryClient = useQueryClient();
  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId!),
    enabled: subjectId !== undefined,
  });
  const observations = useQuery({
    queryKey: ["observations", sid],
    queryFn: () => listObservations(sid),
  });
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

  const topicLabel = (t: { code: string; title: string }) => `${t.title} (${t.code})`;

  return (
    <div className="space-y-6">
      {/* Seeding (spec §7.3). Optional, and deliberately late: it exists so a class
          that has just filled shows something on day one instead of "not enough
          data yet" everywhere. Labelled self-declared wherever it lands (PROD-8),
          and it gives way as marked work arrives. */}
      <SectionCard>
        <CardTitle
          title="Starting estimate"
          description="Where you think this student stands, before their work has been marked. Recorded as self-declared, and it loses weight as real marked work arrives."
        />
        <form onSubmit={onSeed} className="mt-4">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <Field label="Topic to estimate">
              <Select
                value={seed.topic_id}
                onChange={(e) => setSeed({ ...seed, topic_id: e.target.value })}
                required
              >
                <option value="">Choose a topic</option>
                {topics.data?.map((t) => (
                  <option key={t.id} value={t.id}>
                    {topicLabel(t)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Estimated percentage">
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="0–100"
                value={seed.score_pct}
                onChange={(e) => setSeed({ ...seed, score_pct: e.target.value })}
                required
              />
            </Field>
          </div>
          {topics.data?.length === 0 && (
            // The select is empty when the student has no subject yet — say so,
            // rather than leaving a control that cannot be completed (CodeRabbit).
            <p className="mt-2 text-sm text-ink-500">
              No topics to estimate yet — they appear once this student has a subject.
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button type="submit" loading={seedReadiness.isPending}>
              Save estimate
            </Button>
            {/* A live region so assistive technology announces the outcome — the
                  form otherwise signals success only by resetting its fields, which
                  a screen reader does not surface (CodeRabbit). */}
            <p className="text-sm" aria-live="polite">
              {seedReadiness.isError ? (
                <span className="text-risk-600">Could not save the estimate.</span>
              ) : seedReadiness.isSuccess ? (
                <span className="text-ink-500">Estimate saved.</span>
              ) : null}
            </p>
          </div>
        </form>
      </SectionCard>

      <SectionCard>
        <CardTitle
          title="Observations"
          description="Notes from your own judgement. They stay on this profile and never change a readiness score."
        />
        <form onSubmit={onObserve} className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <Field label="Topic" optional>
              <Select
                value={obs.topic_id}
                onChange={(e) => setObs({ ...obs, topic_id: e.target.value })}
              >
                <option value="">General (no topic)</option>
                {topics.data?.map((t) => (
                  <option key={t.id} value={t.id}>
                    {topicLabel(t)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Rating" optional hint="Out of 100">
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="0–100"
                value={obs.rating}
                onChange={(e) => setObs({ ...obs, rating: e.target.value })}
              />
            </Field>
          </div>
          <Field label="What did you notice?">
            <Textarea
              rows={3}
              value={obs.comment}
              onChange={(e) => setObs({ ...obs, comment: e.target.value })}
              required
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={addObservation.isPending}>
              Save observation
            </Button>
            {addObservation.isError && (
              <p role="alert" className="text-sm text-risk-600">
                Could not save the observation.
              </p>
            )}
          </div>
        </form>
        <ObservationList
          observations={observations}
          topicName={(id) => {
            const t = topics.data?.find((x) => x.id === id);
            return t ? t.title : null;
          }}
        />
      </SectionCard>
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
    <section aria-labelledby="saved-observations" className="mt-6 border-t border-line pt-4">
      <h3 id="saved-observations" className="text-sm font-medium text-ink-900">
        Saved observations
      </h3>
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
  if (observations.isLoading) {
    return (
      <div className="mt-3">
        <SectionSkeleton rows={2} label="Loading observations" />
      </div>
    );
  }
  if (observations.isError)
    return (
      <p role="alert" className="mt-2 text-sm text-risk-600">
        Could not load observations.
      </p>
    );
  const rows = observations.data ?? [];
  if (rows.length === 0) return <p className="mt-2 text-sm text-ink-500">No observations yet.</p>;
  return (
    <ul className="mt-2 divide-y divide-line">
      {rows.map((o) => (
        <li key={o.id} className="py-2.5 text-sm">
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
