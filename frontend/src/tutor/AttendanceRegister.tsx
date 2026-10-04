import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAttendance,
  setAttendance,
  type AttendanceRow,
  type AttendanceState,
} from "../api/lessons";
import { friendlyError } from "../lib/errors";
import { Button } from "../components/controls";

const SOURCE_LABEL: Record<NonNullable<AttendanceRow["source"]>, string | null> = {
  tutor: "set by you",
  zoom: "from Zoom",
  google_meet: "from Meet",
};

/** The register for one lesson. An unmarked student reads "Not taken", never
 *  "Absent": no mark means nobody recorded it (`PROD-2`). Pressing the active
 *  choice again clears it, so a slip can be undone. The tutor has the final say
 *  (`PROD-7`): an online lesson's register is editable too, and its marks say
 *  where they came from ("from Zoom", "from Meet", "set by you"). */
export default function AttendanceRegister({
  lessonId,
  online = false,
}: {
  lessonId: number;
  online?: boolean;
}) {
  const queryClient = useQueryClient();
  const key = ["lesson-attendance", lessonId];
  const register = useQuery({ queryKey: key, queryFn: () => getAttendance(lessonId) });
  const mark = useMutation({
    mutationFn: (v: { studentId: number; state: AttendanceState | null }) =>
      setAttendance(lessonId, [{ student_id: v.studentId, state: v.state }]),
    onSuccess: (rows) => queryClient.setQueryData(key, rows),
  });

  if (register.isLoading) return <p className="text-sm text-ink-500">Loading the register…</p>;
  if (register.isError) {
    return (
      <p role="alert" className="text-sm text-risk-600">
        {friendlyError(register.error)}
      </p>
    );
  }
  const rows = register.data ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-ink-500">No students in this class yet.</p>;
  }

  return (
    <div>
      <ul className="divide-y divide-line">
        {rows.map((row) => (
          <li key={row.student_id} className="flex items-center justify-between gap-3 py-2">
            <span className="min-w-0 text-sm text-ink-900">{row.name}</span>
            <span className="flex items-center gap-2">
              {row.state === null && <span className="text-xs text-ink-500">Not taken</span>}
              {online && row.state !== null && row.source && (
                <span className="text-xs text-ink-500">{SOURCE_LABEL[row.source]}</span>
              )}
              {(["present", "absent"] as const).map((state) => {
                const active = row.state === state;
                return (
                  <Button
                    key={state}
                    size="sm"
                    variant={active ? "primary" : "secondary"}
                    aria-pressed={active}
                    aria-label={`${state === "present" ? "Present" : "Absent"}: ${row.name}`}
                    disabled={mark.isPending}
                    onClick={() =>
                      mark.mutate({ studentId: row.student_id, state: active ? null : state })
                    }
                  >
                    {state === "present" ? "Present" : "Absent"}
                  </Button>
                );
              })}
            </span>
          </li>
        ))}
      </ul>
      {mark.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {friendlyError(mark.error)}
        </p>
      )}
    </div>
  );
}
