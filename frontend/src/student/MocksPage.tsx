import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { myMocks } from "../api/mocks";
import { listSubjects } from "../api/groups";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { SubjectSection } from "../components/SubjectGroups";
import { EmptyState, SectionCard } from "../components/ui";
import { groupBySubject } from "../lib/subjectGroups";

export default function MocksPage() {
  const mocks = useQuery({ queryKey: ["my-mocks"], queryFn: myMocks });
  // The mock row carries only `subject_id`; the names come from the subject
  // list the student can already see. A missing name renders as nothing rather
  // than as "Subject 4" (`PROD-2`).
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const subjectName = new Map(subjects.data?.map((s) => [s.id, s.name]));
  // Grouped only once the names have arrived: without them every item would
  // sit under "Other subject", and if the request fails they never will.
  const groups = groupBySubject(mocks.data, subjects.isSuccess ? subjects.data : undefined);
  const grouped = subjects.isSuccess && groups.length > 1;

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Mocks"
        description="The mocks your tutor has set you. The clock starts when you open one, and it runs on our servers — not on your device."
      />

      {mocks.isPending ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading your mocks" />
        </SectionCard>
      ) : mocks.isError ? (
        // Without this a failed request renders as a bare heading, which reads
        // as "your tutor has set you nothing" — the one thing a student must
        // not be told when the truth is that we could not ask.
        <ErrorState
          title="We couldn't load your mocks just now."
          error={mocks.error}
          onRetry={() => void mocks.refetch()}
        />
      ) : mocks.data.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="Your tutor hasn't set you a mock yet."
            hint="When they do, it will appear here."
          />
        </SectionCard>
      ) : (
        // Newest first is the server's own order (`Mock.id` descending).
        // Several subjects get a heading each; one subject needs none, and
        // keeps its name on each card as before.
        <div className="space-y-6">
          {(grouped ? groups : [{ id: "all", subject: null, items: mocks.data }]).map((g) => {
            const list = (
              <ul className="grid gap-3 sm:grid-cols-2">
                {g.items.map((m) => {
                  const facts = [
                    grouped ? null : subjectName.get(m.subject_id),
                    m.duration_minutes ? `${m.duration_minutes} minutes` : null,
                    m.total_marks ? `${m.total_marks} marks` : null,
                  ].filter(Boolean);
                  return (
                    <li key={m.id}>
                      <Link
                        to={`/student/mocks/${m.id}`}
                        className="block h-full rounded-xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(44,26,14,0.06)] transition-colors hover:border-brand-500"
                      >
                        <div className="font-medium text-ink-900">{m.title}</div>
                        {facts.length > 0 && (
                          <div className="mt-1 text-sm text-ink-500">{facts.join(" · ")}</div>
                        )}
                        {/* `sat_on` is the date the *tutor* set the mock for and says
                      nothing about whether this student handed in — the server
                      sends their own status on the row, so the list does not
                      ask once per mock. */}
                        {m.my_submission_status ? (
                          <div className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-ok-100 px-2 py-0.5 text-xs font-medium text-ok-700">
                            <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
                            You have handed this in
                          </div>
                        ) : (
                          <div className="mt-3 inline-block rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-ink-700">
                            Not handed in yet
                          </div>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            );
            return grouped ? (
              <SubjectSection key={g.id} subject={g.subject} level="h2">
                {list}
              </SubjectSection>
            ) : (
              <div key={g.id}>{list}</div>
            );
          })}
        </div>
      )}
    </div>
  );
}
