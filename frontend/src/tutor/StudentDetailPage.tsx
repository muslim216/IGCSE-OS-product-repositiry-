import { useRef, useState, type KeyboardEvent } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { studentReadiness } from "../api/readiness";
import { ApiError } from "../api/client";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
import StudentSummary from "./student/StudentSummary";
import ProgressTab from "./student/ProgressTab";
import WorkTab from "./student/WorkTab";
import NotesTab, { type ObsDraft, type SeedDraft } from "./student/NotesTab";
import AboutTab from "./student/AboutTab";

const TABS = [
  { id: "progress", label: "Progress" },
  { id: "work", label: "Work" },
  { id: "notes", label: "Notes" },
  { id: "about", label: "About" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function StudentDetailPage() {
  const { studentId } = useParams();
  const sid = Number(studentId);
  const [params, setParams] = useSearchParams();
  const groupId = params.get("group");
  const subjectIdParam = params.get("subject");
  // The open tab is in the URL so Back and a shared link both land on it; an
  // unknown value is the default rather than an empty page.
  const tab: TabId = TABS.find((t) => t.id === params.get("tab"))?.id ?? "progress";
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const readiness = useQuery({
    queryKey: ["student-readiness", sid],
    queryFn: () => studentReadiness(sid),
  });
  const [selectedTopic, setSelectedTopic] = useState<number | null>(null);
  // Drafts live here, not in the tabs, so unsaved text survives a tab switch.
  const [obs, setObs] = useState<ObsDraft>({ topic_id: "", comment: "", rating: "" });
  const [seed, setSeed] = useState<SeedDraft>({ topic_id: "", score_pct: "" });

  const subjectId = subjectIdParam
    ? Number(subjectIdParam)
    : readiness.data?.subjects[0]?.subject_id;

  function open(id: TabId) {
    const next = new URLSearchParams(params);
    next.set("tab", id);
    setParams(next);
    tabRefs.current[id]?.focus();
  }

  function onTabKey(e: KeyboardEvent, i: number) {
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    open(TABS[(to + TABS.length) % TABS.length].id);
  }

  if (readiness.isLoading) return <PageSkeleton label="Loading the student" />;
  const back = groupId
    ? { to: `/tutor/groups/${groupId}/students`, label: "Back to class" }
    : { to: "/tutor/classes", label: "All classes" };
  if (readiness.isError && readiness.error instanceof ApiError && readiness.error.status === 404) {
    return (
      <NotFoundState
        title="We couldn't find that student"
        body="They may have left your classes, or the link may be wrong."
        back={back}
      />
    );
  }
  if (readiness.isError || !readiness.data) {
    return (
      <ErrorState
        title="This student's profile didn't load"
        error={readiness.error}
        onRetry={() => readiness.refetch()}
      />
    );
  }
  const r = readiness.data;

  return (
    <div>
      <PageHeader title={r.student_name} back={back} />
      <StudentSummary readiness={r} />

      <div role="tablist" aria-label="Student sections" className="mb-6 flex border-b border-line">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[t.id] = el;
            }}
            type="button"
            role="tab"
            id={`student-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`student-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => open(t.id)}
            onKeyDown={(e) => onTabKey(e, i)}
            className={`min-h-11 flex-1 border-b-2 px-3 text-sm font-medium sm:flex-none sm:px-5 ${
              tab === t.id
                ? "border-brand-600 text-ink-900"
                : "border-transparent text-ink-500 hover:text-ink-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Only the open tab is mounted, so a closed tab asks for nothing. */}
      <div role="tabpanel" id={`student-panel-${tab}`} aria-labelledby={`student-tab-${tab}`}>
        {/* The sections below start at h3 in places; this keeps the outline h1, h2, h3. */}
        <h2 className="sr-only">{TABS.find((t) => t.id === tab)?.label}</h2>
        {tab === "progress" && (
          <ProgressTab
            studentId={sid}
            readiness={r}
            selectedTopic={selectedTopic}
            setSelectedTopic={setSelectedTopic}
          />
        )}
        {tab === "work" && <WorkTab studentId={sid} />}
        {tab === "notes" && (
          <NotesTab
            studentId={sid}
            subjectId={subjectId}
            obs={obs}
            setObs={setObs}
            seed={seed}
            setSeed={setSeed}
          />
        )}
        {tab === "about" && <AboutTab studentId={sid} name={r.student_name} />}
      </div>
    </div>
  );
}
