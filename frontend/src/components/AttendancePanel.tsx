import { useQuery } from "@tanstack/react-query";
import {
  myAttendance,
  studentAttendance,
  type ClassAttendance,
  type StudentAttendance,
} from "../api/attendance";
import { ABSENT } from "../lib/labels";
import { shortDay } from "../lib/planDates";
import { EmptyState, SectionCard, SectionHeader } from "./ui";

/**
 * Attendance for one student, shown to all three roles beside readiness and
 * never in it (AV-33). `own` reads the signed-in student's record from the
 * token; otherwise `studentId` is a tutor's student or a parent's child.
 *
 * The rate is present out of lessons that were marked. A lesson nobody took
 * attendance for is stated as "not taken" and left out of the rate — it is not
 * absent (`PROD-2`) — and with nothing marked there is no rate at all, never
 * 0% and never an empty bar (`UX-19`).
 */
export const NO_ATTENDANCE = "No attendance recorded yet";

export function rateSentence(present: number, absent: number, notTaken: number): string {
  const marked = present + absent;
  if (marked === 0) return NO_ATTENDANCE;
  const base = `Present at ${present} of ${marked} lessons`;
  return notTaken > 0 ? `${base} · ${notTaken} not taken` : base;
}

/** A 200 whose body is not the contract reads as a failed load, not a crash. */
function wellFormed(data: StudentAttendance | undefined): data is StudentAttendance {
  return (
    Array.isArray(data?.classes) &&
    data.classes.every(
      (c) =>
        c !== null &&
        typeof c === "object" &&
        typeof c.group_id === "number" &&
        typeof c.present === "number" &&
        typeof c.absent === "number" &&
        typeof c.not_taken === "number" &&
        Array.isArray(c.recent),
    )
  );
}

export default function AttendancePanel({
  studentId,
  own = false,
}: {
  studentId: number;
  own?: boolean;
}) {
  const attendance = useQuery({
    queryKey: ["attendance", own ? "me" : studentId],
    queryFn: () => (own ? myAttendance() : studentAttendance(studentId)),
  });

  if (attendance.isPending) return null;

  return (
    <SectionCard>
      <SectionHeader
        title="Attendance"
        description="Recorded by the tutor. Not part of the readiness score."
      />
      {attendance.isError || !wellFormed(attendance.data) ? (
        // A malformed 200 reads as a failed load rather than crashing the page.
        <p className="mt-3 text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : attendance.data.classes.length === 0 ? (
        <EmptyState title={NO_ATTENDANCE} />
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {attendance.data.classes.map((c) => (
            <ClassRow key={c.group_id} cls={c} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

const STATE_LABEL = { present: "Present", absent: "Absent" } as const;

function ClassRow({ cls }: { cls: ClassAttendance }) {
  return (
    <li className="py-3">
      <p className="text-sm font-medium text-ink-900">{cls.group_name}</p>
      <p className="mt-0.5 text-sm text-ink-700">
        {rateSentence(cls.present, cls.absent, cls.not_taken)}
      </p>
      {cls.recent.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-500">
          {cls.recent.map((l) => (
            <li key={l.lesson_id}>
              {shortDay(l.date)}
              {l.start_time ? ` ${l.start_time.slice(0, 5)}` : ""}
              {l.mode === "online" ? " · online" : ""}
              {" · "}
              {l.state ? STATE_LABEL[l.state] : "Not taken"}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
