import RenameStudent from "../RenameStudent";
import StudentContacts from "../StudentContacts";
import LinkedParents from "../../components/LinkedParents";
import DownloadChildData from "../../components/DownloadChildData";
import DeleteChildData from "../../components/DeleteChildData";
import { SectionCard, SectionHeader } from "../../components/ui";

// Every account and destructive control lives here and nowhere else.
export default function AboutTab({
  studentId: sid,
  name,
}: Readonly<{ studentId: number; name: string }>) {
  return (
    <div className="space-y-6">
      <RenameStudent studentId={sid} name={name} />

      {/* Where this learner and their parents are reached; each address is
          confirmed here before anything is sent to it (threat review F5). */}
      <StudentContacts studentId={sid} />

      <LinkedParents studentId={sid} />

      <SectionCard>
        <SectionHeader
          title="Download this student's data"
          description="Everything Avora holds about them, with their uploaded pages, as a ZIP. Kept for seven days."
        />
        <div className="mt-4">
          <DownloadChildData key={sid} asker="tutor" studentId={sid} name={name} />
          <div className="mt-4">
            <DeleteChildData key={sid} asker="tutor" studentId={sid} name={name} />
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
