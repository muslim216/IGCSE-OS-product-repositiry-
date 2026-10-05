import { useGroupContext } from "../GroupLayout";
import RecordLessonForm from "../RecordLessonForm";
import RecordedLessons from "../RecordedLessons";
import TeachingPlanInputs from "../TeachingPlanInputs";
import TeachingPlanView from "../TeachingPlanView";
import TimetableEditor from "../TimetableEditor";

export default function ScheduleTab() {
  const { group, groupId } = useGroupContext();

  return (
    <div className="space-y-6">
      <RecordLessonForm key={`record-${groupId}`} groupId={groupId} subjectId={group.subject.id} />
      <RecordedLessons key={`recorded-${groupId}`} groupId={groupId} />

      <TimetableEditor groupId={groupId} />

      <TeachingPlanInputs key={groupId} groupId={groupId} />
      <TeachingPlanView key={`view-${groupId}`} groupId={groupId} subjectId={group.subject.id} />
    </div>
  );
}
