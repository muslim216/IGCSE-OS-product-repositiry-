import { useState } from "react";
import { Button } from "../../components/controls";
import { useGroupContext } from "../GroupLayout";
import RecordLessonForm from "../RecordLessonForm";
import RecordedLessons from "../RecordedLessons";
import TeachingPlanInputs from "../TeachingPlanInputs";
import TeachingPlanView from "../TeachingPlanView";
import TimetableEditor from "../TimetableEditor";

/** A link from a lesson reminder or today's agenda lands here with `?slot=` or
 *  `?date=`: the form must already be open for it to pre-fill. */
function linkedToRecord(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.has("slot") || params.has("date");
}

/** The plan first; recording and settings are one button each. */
export default function ScheduleTab() {
  const { group, groupId } = useGroupContext();
  const [recording, setRecording] = useState(linkedToRecord);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {!recording && <Button onClick={() => setRecording(true)}>Record a lesson</Button>}
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
        <RecordLessonForm
          key={`record-${groupId}`}
          groupId={groupId}
          subjectId={group.subject.id}
          onClose={() => setRecording(false)}
        />
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
