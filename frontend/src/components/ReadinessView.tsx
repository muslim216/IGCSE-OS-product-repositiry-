import type { SubjectReadiness } from "../api/readiness";

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-600";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-red-500";
}

const CONFIDENCE_NOTE: Record<string, string> = {
  low: "Early estimate — more work needed to be sure",
  medium: "Fairly confident",
  high: "Confident",
  none: "Not enough data yet",
};

export function SubjectReadinessCard({
  subject,
  onTopicClick,
}: {
  subject: SubjectReadiness;
  onTopicClick?: (topicId: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-white p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-slate-800">{subject.subject_name}</h3>
            {subject.is_updating && (
              <span
                className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                title="New evidence has come in — this score is being recalculated."
              >
                Updating…
              </span>
            )}
          </div>
          <p className="text-sm text-slate-500">{subject.exam_board}</p>
        </div>
        {subject.score !== null ? (
          <div className="text-right">
            <div className={`text-3xl font-bold ${scoreColor(subject.score)}`}>
              {Math.round(subject.score)}%
            </div>
            <div className="text-sm text-slate-500">
              Predicted grade{" "}
              <span className="font-semibold text-slate-700">{subject.predicted_grade}</span>{" "}
              <span className="text-xs text-slate-400">(estimate)</span>
            </div>
          </div>
        ) : (
          <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
            Not enough data yet
          </span>
        )}
      </div>

      {subject.is_updating && subject.score !== null && (
        <p className="mt-2 text-xs text-blue-700">
          Showing the last calculated score while a new one is worked out.
        </p>
      )}

      {subject.rationale && (
        <p className="mt-3 text-sm text-slate-600">{subject.rationale}</p>
      )}

      {subject.recommended_revision && (
        <div className="mt-3 rounded bg-slate-50 p-3 text-sm text-slate-600">
          <span className="font-medium text-slate-700">What to do next: </span>
          {subject.recommended_revision}
        </div>
      )}

      {subject.weak_topics.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-slate-600">Focus on these topics</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {subject.weak_topics.map((t) => (
              <button
                key={t.topic_id}
                onClick={() => onTopicClick?.(t.topic_id)}
                className="rounded-full bg-red-50 px-2.5 py-1 text-xs text-red-700 hover:bg-red-100"
                title={`${Math.round(t.score)}%`}
              >
                {t.topic_code} {t.topic_title}
              </button>
            ))}
          </div>
        </div>
      )}

      {subject.topics.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-slate-600">Topic breakdown</p>
          <div className="mt-2 space-y-1.5">
            {subject.topics.map((t) => (
              <button
                key={t.topic_id}
                onClick={() => onTopicClick?.(t.topic_id)}
                className="block w-full text-left"
                title={CONFIDENCE_NOTE[t.confidence]}
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="w-28 shrink-0 truncate text-slate-500">{t.topic_code}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={`h-full ${barColor(t.score)}`}
                      style={{ width: `${t.score}%` }}
                    />
                  </div>
                  <span className={`w-10 shrink-0 text-right ${scoreColor(t.score)}`}>
                    {Math.round(t.score)}%
                  </span>
                  {t.confidence === "low" && (
                    <span className="text-xs text-slate-400" title="Low confidence">
                      ?
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
