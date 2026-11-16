import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { listLessons } from "../../api/groups";
import { getPlan } from "../../api/teachingPlan";
import { Button } from "../../components/controls";
import { useGroupContext } from "../GroupLayout";
import RecordLessonForm from "../RecordLessonForm";
import RecordedLessons from "../RecordedLessons";
import TeachingPlanInputs from "../TeachingPlanInputs";
import TeachingPlanView from "../TeachingPlanView";
import TimetableEditor from "../TimetableEditor";

/** The plan first; recording and settings are one button each. */
export default function ScheduleTab() {
  const { group, groupId } = useGroupContext();
  const [params, setParams] = useSearchParams();

  // A link from a lesson reminder or today's agenda lands here with `?slot=` or
  // `?date=`: the form must be open for it to pre-fill. Read from the router, so
  // following such a link while already on this tab opens it too.
  const recordLink = params.has("slot") || params.has("date") ? params.toString() : "";
  const [recording, setRecording] = useState(recordLink !== "");
  const [seenRecordLink, setSeenRecordLink] = useState(recordLink);
  if (recordLink !== seenRecordLink) {
    setSeenRecordLink(recordLink);
    if (recordLink !== "") setRecording(true);
  }
  const recordButton = useRef<HTMLButtonElement>(null);
  const recordForm = useRef<HTMLDivElement>(null);
  // Mounted for good, so a change to its text is announced.
  const [recordedNote, setRecordedNote] = useState("");

  useEffect(() => {
    if (recording) recordForm.current?.querySelector("h2")?.focus();
  }, [recording]);

  // Plan settings opens by itself for a class that has no plan yet or no
  // timetable (the setup links lead here), or when the link asks (`?settings=1`).
  // It opens once: saving the timetable must not close it under the tutor who
  // is about to fill in the plan, and the tutor can still close it by hand.
  const plan = useQuery({ queryKey: ["plan", groupId], queryFn: () => getPlan(groupId) });
  const lessons = useQuery({ queryKey: ["lessons", groupId], queryFn: () => listLessons(groupId) });
  const needsSetup =
    (plan.isSuccess && !plan.data.draft && !plan.data.accepted) ||
    (lessons.isSuccess && lessons.data.length === 0);
  const wantsSettings = params.get("settings") === "1" || needsSetup;
  const [settingsOpen, setSettingsOpen] = useState(wantsSettings);
  const [autoOpened, setAutoOpened] = useState(wantsSettings);
  if (wantsSettings && !autoOpened) {
    setAutoOpened(true);
    setSettingsOpen(true);
  }

  function closeRecording(saved: boolean) {
    setRecording(false);
    if (saved) setRecordedNote("Lesson recorded.");
    // The button never unmounted, so focus can go back to it straight away.
    recordButton.current?.focus();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center">
          <Button
            ref={recordButton}
            aria-expanded={recording}
            aria-controls={`record-form-${groupId}`}
            onClick={() => {
              setRecordedNote("");
              setRecording((r) => !r);
            }}
          >
            Record a lesson
          </Button>
          <span role="status" aria-live="polite" className="ml-3 text-sm text-ok-700 empty:ml-0">
            {recordedNote}
          </span>
        </div>
        <Button
          variant="secondary"
          aria-expanded={settingsOpen}
          aria-controls={`plan-settings-${groupId}`}
          onClick={() => setSettingsOpen((o) => !o)}
        >
          Plan settings
        </Button>
      </div>
      {recording && (
        <div id={`record-form-${groupId}`} ref={recordForm}>
          <RecordLessonForm
            key={`record-${groupId}-${recordLink}`}
            groupId={groupId}
            subjectId={group.subject.id}
            onClose={closeRecording}
            onLinkConsumed={() =>
              setParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  next.delete("slot");
                  next.delete("date");
                  return next;
                },
                { replace: true },
              )
            }
          />
        </div>
      )}
      {/* Kept mounted while closed so a half-typed input is never lost, and so
          the same requests are made as before. */}
      <section
        id={`plan-settings-${groupId}`}
        aria-label="Plan settings"
        hidden={!settingsOpen}
        className="space-y-6"
      >
        <TimetableEditor groupId={groupId} />
        <TeachingPlanInputs key={groupId} groupId={groupId} />
      </section>

      <TeachingPlanView key={`view-${groupId}`} groupId={groupId} subjectId={group.subject.id} />
      <RecordedLessons key={`recorded-${groupId}`} groupId={groupId} />
    </div>
  );
}
