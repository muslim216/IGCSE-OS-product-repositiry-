import { useRef, useState, type KeyboardEvent } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createObservation, seedStudentReadiness, studentReadiness } from "../api/readiness";
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

// Keyed on the student, so the drafts, the picked topic and the pending saves
// below never carry from one student to the next when only the URL changes.
export default function StudentDetailPage() {
  const { studentId } = useParams();
  return <StudentDetail key={studentId} />;
}

function StudentDetail() {
  const { studentId } = useParams();
  const sid = Number(studentId);
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const groupId = params.get("group");
  const subjectIdParam = params.get("subject");
  // The open tab is in the URL so Back and a shared link both land on it; an
  // unknown value is the default rather than an empty page.
  const tab: TabId = TABS.find((t) => t.id === params.get("tab"))?.id ?? "progress";
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});

  const readiness = useQuery({
    queryKey: ["student-readiness", sid],
    queryFn: () => studentReadiness(sid),
  });
  const [selectedTopic, setSelectedTopic] = useState<number | null>(null);
  // Drafts live here, not in the tabs, so unsaved text survives a tab switch.
  const [obs, setObs] = useState<ObsDraft>({ topic_id: "", comment: "", rating: "" });
  const [seed, setSeed] = useState<SeedDraft>({ topic_id: "", score_pct: "" });

  // The saves live here for the same reason as the drafts: a tab unmounts, and a
  // save still in flight (or its error) must be there when the tutor comes back,
  // or the button looks free and a second click sends a duplicate.
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

  const subjectId = subjectIdParam
    ? Number(subjectIdParam)
    : readiness.data?.subjects[0]?.subject_id;

  function open(id: TabId) {
    // Already open: nothing to change, so no history entry for Back to step
    // through (this includes Progress on a bare URL).
    if (id !== tab) {
      const next = new URLSearchParams(params);
      next.set("tab", id);
      setParams(next);
    }
    tabRefs.current[id]?.focus();
  }

  // Manual activation: each panel loads over the network, so arrowing across
  // the bar only moves focus; Enter, Space or a click opens the tab.
  function onTabKey(e: KeyboardEvent, i: number) {
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    tabRefs.current[TABS[(to + TABS.length) % TABS.length].id]?.focus();
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
            aria-controls={tab === t.id ? `student-panel-${t.id}` : undefined}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => open(t.id)}
            onKeyDown={(e) => onTabKey(e, i)}
            className={`min-h-11 flex-1 border-b-2 px-3 text-sm font-medium sm:flex-none sm:px-5 ${
              tab === t.id
                ? "-mb-px border-brand-600 text-ink-900"
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
            addObservation={addObservation}
            seedReadiness={seedReadiness}
          />
        )}
        {tab === "about" && <AboutTab studentId={sid} name={r.student_name} />}
      </div>
    </div>
  );
}
