import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { generateClassBrief, type Group } from "../../api/groups";
import GuidancePanel from "../../components/GuidancePanel";
import LearningLoopStrip from "../../components/LearningLoopStrip";
import { EmptyState, SectionCard, SectionHeader } from "../../components/ui";

/**
 * Section C: how evidence becomes the next teaching decision. The guidance is
 * prepared only when the educator asks for it — it reads their own marked work,
 * and it never claims more than that evidence supports.
 */
export default function EvidenceToAction({
  groups,
  defaultGroupId,
}: {
  groups: Group[] | undefined;
  /** The class the educator is teaching next, when there is one. */
  defaultGroupId: number | undefined;
}) {
  const options = groups ?? [];
  const [chosen, setChosen] = useState<string>("");
  const [briefs, setBriefs] = useState<Record<number, string>>({});
  const [error, setError] = useState("");

  const selected =
    chosen || (defaultGroupId ? String(defaultGroupId) : options[0] ? String(options[0].id) : "");
  const selectedId = Number(selected);
  const selectedGroup = options.find((g) => g.id === selectedId);

  const brief = useMutation({
    mutationFn: () => generateClassBrief(selectedId),
    onSuccess: (data) => {
      setBriefs((b) => ({ ...b, [selectedId]: data.brief }));
      setError("");
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Guidance couldn't be prepared right now. Try again in a moment.",
      ),
  });

  return (
    <SectionCard>
      <SectionHeader
        title="Evidence to action"
        description="How today's work becomes your next teaching decision"
      />

      <div className="mt-5">
        <LearningLoopStrip />
      </div>

      <div className="mt-5">
        {options.length === 0 ? (
          <EmptyState
            title="Create your first class to see guidance here."
            hint="Guidance reads the marked homework and assessments of a class you teach."
            action={
              <Link to="/tutor/classes" className="font-medium text-brand-600 hover:text-brand-700">
                Go to classes →
              </Link>
            }
          />
        ) : (
          <>
            <label className="block text-sm text-ink-700">
              Class
              <select
                value={selected}
                onChange={(e) => {
                  setChosen(e.target.value);
                  setError("");
                }}
                className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink-900 focus:border-brand-700 focus:outline-none"
              >
                {options.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name} — {g.subject.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="mt-3">
              <GuidancePanel
                evidenceNote={`Based on ${
                  selectedGroup ? `${selectedGroup.name}'s` : "this class's"
                } marked homework, assessments and readiness evidence.`}
                body={briefs[selectedId]}
                pending={brief.isPending}
                error={error || undefined}
                placeholder="Recent homework and assessment evidence can be read together into a short pre-lesson note: what to focus on today, and who may need extra attention."
                action={
                  <button
                    type="button"
                    onClick={() => brief.mutate()}
                    disabled={brief.isPending}
                    className="flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas transition hover:bg-brand-700 disabled:opacity-50"
                  >
                    <Sparkles aria-hidden className="h-4 w-4" />
                    {brief.isPending
                      ? "Preparing…"
                      : briefs[selectedId]
                        ? "Prepare again"
                        : "Prepare guidance"}
                  </button>
                }
                secondaryActions={
                  <>
                    <Link
                      to="/tutor/homework"
                      className="text-sm font-medium text-brand-600 hover:text-brand-700"
                    >
                      Review marking queue →
                    </Link>
                    <Link
                      to="/tutor/readiness"
                      className="text-sm font-medium text-brand-600 hover:text-brand-700"
                    >
                      Open class readiness →
                    </Link>
                  </>
                }
              />
            </div>
          </>
        )}
      </div>
    </SectionCard>
  );
}
