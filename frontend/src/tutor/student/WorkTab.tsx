import { ReportsPanel } from "../../components/ReportsPanel";
import { EarlierAttempts } from "../EarlierAttempts";

export default function WorkTab({ studentId }: { studentId: number }) {
  return (
    <div className="space-y-6">
      <EarlierAttempts studentId={studentId} />
      <ReportsPanel studentId={studentId} audiences={["student", "tutor", "parent"]} />
    </div>
  );
}
