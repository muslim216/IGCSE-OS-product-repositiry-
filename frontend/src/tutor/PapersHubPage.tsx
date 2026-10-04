import { FileText, Layers, PenLine } from "lucide-react";
import { PageHeader } from "../components/page";
import { ShelfSection, type Shelf } from "./LibraryPage";

/**
 * One door for everything a student sits: past papers, booklets of them, and
 * mocks. They were three cards on the Library shelf; they are one nav item now
 * because they are one job: getting exam material in front of students and
 * their results back.
 */
const PAPERS: Shelf[] = [
  {
    to: "/tutor/past-papers",
    label: "Past papers",
    hint: "Add full past papers for every student taking that subject to sit.",
    icon: FileText,
  },
  {
    to: "/tutor/booklets",
    label: "Booklets",
    hint: "One PDF holding several papers, and the AI reads out what is inside for you to check.",
    icon: Layers,
  },
  {
    to: "/tutor/mocks",
    label: "Mocks",
    hint: "Enter a class's mock or test marks and look back at what you have recorded.",
    icon: PenLine,
  },
];

export default function PapersHubPage() {
  return (
    <div>
      <PageHeader
        title="Papers & mocks"
        description="The exam material your students sit, and where their mock results go."
      />
      <ShelfSection
        title="Exam material"
        description="Add papers, split booklets, record mocks."
        items={PAPERS}
      />
    </div>
  );
}
