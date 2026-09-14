import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myMocks } from "../api/mocks";
import { listSubjects } from "../api/groups";

export default function MocksPage() {
  const mocks = useQuery({ queryKey: ["my-mocks"], queryFn: myMocks });
  // The mock row carries only `subject_id`; the names come from the subject
  // list the student can already see. A missing name renders as nothing rather
  // than as "Subject 4" (`PROD-2`).
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const subjectName = new Map(subjects.data?.map((s) => [s.id, s.name]));

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-ink-900">Mocks</h2>
        <p className="text-sm text-ink-500">
          The mocks your tutor has set you. The clock starts when you open one, and it runs on our
          servers — not on your device.
        </p>
      </div>

      {mocks.isLoading && <p className="text-ink-500">Loading…</p>}

      {/* Newest first is the server's own order (`Mock.id` descending). */}
      <div className="grid gap-3 sm:grid-cols-2">
        {mocks.data?.map((m) => (
          <Link
            key={m.id}
            to={`/student/mocks/${m.id}`}
            className="rounded-lg border border-line bg-surface p-4 hover:border-brand-500"
          >
            <div className="font-medium text-ink-900">{m.title}</div>
            <div className="mt-1 text-sm text-ink-500">
              {subjectName.get(m.subject_id)}
              {m.duration_minutes ? ` · ${m.duration_minutes} minutes` : ""}
              {m.total_marks ? ` · ${m.total_marks} marks` : ""}
            </div>
            {/* `sat_on` is the date the *tutor* set the mock for and says
                nothing about whether this student handed in — the server sends
                their own status on the row, so the list does not ask once per
                mock. */}
            <div className="mt-1 text-sm text-ink-500">
              {m.my_submission_status ? "You have handed this in" : "Not handed in yet"}
            </div>
          </Link>
        ))}
      </div>

      {mocks.data?.length === 0 && (
        <p className="text-ink-500">Your tutor hasn't set you a mock yet.</p>
      )}
    </div>
  );
}
