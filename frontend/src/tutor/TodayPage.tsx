import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { generateClassBrief, myTodayLessons } from "../api/groups";
import { Markdown } from "../components/Markdown";
import { ApiError } from "../api/client";

export default function TodayPage() {
  const lessons = useQuery({ queryKey: ["today-lessons"], queryFn: myTodayLessons });
  const [briefs, setBriefs] = useState<Record<number, string>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});

  const brief = useMutation({
    mutationFn: (groupId: number) => generateClassBrief(groupId),
  });

  function requestBrief(groupId: number) {
    setErrors((e) => ({ ...e, [groupId]: "" }));
    brief.mutate(groupId, {
      onSuccess: (data) => setBriefs((b) => ({ ...b, [groupId]: data.brief })),
      onError: (err) =>
        setErrors((e) => ({
          ...e,
          [groupId]: err instanceof ApiError ? err.message : String(err),
        })),
    });
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Today's lessons</h2>
        <p className="text-sm text-slate-500">
          Your groups today, with an optional AI-written brief to jog your memory.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {lessons.data?.map((l) => (
          <div key={l.id} className="rounded-lg border bg-white p-4">
            <div className="flex items-center justify-between">
              <h3 className="font-medium text-slate-800">{l.group_name}</h3>
              <span className="text-sm text-slate-500">{l.start_time.slice(0, 5)}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {l.subject_name} · {l.duration_min} min{l.title ? ` · ${l.title}` : ""}
            </p>
            <button
              onClick={() => requestBrief(l.group_id)}
              disabled={brief.isPending && brief.variables === l.group_id}
              className="mt-3 rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {brief.isPending && brief.variables === l.group_id ? "Writing…" : "Generate class brief"}
            </button>
            {errors[l.group_id] && (
              <p className="mt-2 text-sm text-red-600">{errors[l.group_id]}</p>
            )}
            {briefs[l.group_id] && (
              <div className="mt-3 rounded-md bg-slate-50 p-3">
                <Markdown content={briefs[l.group_id]} />
              </div>
            )}
          </div>
        ))}
        {lessons.data?.length === 0 && (
          <p className="text-sm text-slate-500">No lessons scheduled for today.</p>
        )}
      </div>
    </div>
  );
}
