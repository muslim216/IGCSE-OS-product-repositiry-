import { Link } from "react-router-dom";
import {
  BookOpen,
  ChevronRight,
  ClipboardList,
  FileText,
  Gauge,
  Layers,
  PenLine,
  Ruler,
  Scale,
  Tags,
  Settings as SettingsIcon,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "../components/page";
import { SectionHeader } from "../components/ui";

/**
 * Library is the tutor's shelf: the reference and content surfaces that don't
 * belong in the daily workflow (Today · Classes · Review) but must stay one tap
 * away. Collapsing nine nav items to four moved these here rather than deleting
 * them — every destination the old sidebar offered is still reachable.
 */
interface Shelf {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
}

const CONTENT: Shelf[] = [
  {
    to: "/tutor/past-papers",
    label: "Past papers",
    hint: "Add full past papers for every student taking that subject to sit.",
    icon: FileText,
  },
  {
    to: "/tutor/booklets",
    label: "Booklets",
    hint: "One PDF holding several papers — the AI reads out what's inside and you check the list.",
    icon: Layers,
  },
  {
    to: "/tutor/mocks",
    label: "Mocks",
    hint: "Enter and track mock results.",
    icon: PenLine,
  },
  {
    to: "/tutor/syllabuses",
    label: "Syllabuses",
    hint: "Upload a syllabus to build its topic tree.",
    icon: BookOpen,
  },
  {
    to: "/tutor/teaching-guidance",
    label: "Teaching guidance",
    hint: "Your scheme of work per subject, kept for the teaching plan to use.",
    icon: ClipboardList,
  },
  {
    to: "/tutor/readiness",
    label: "Class readiness",
    hint: "Drill into a class and flag learners who need attention.",
    icon: Gauge,
  },
];

const SETTINGS: Shelf[] = [
  {
    to: "/tutor/marking-rules",
    label: "AI marking agreement",
    hint: "How you want work in a subject marked, in your own words.",
    icon: Scale,
  },
  {
    to: "/tutor/boundaries",
    label: "Grade boundaries",
    hint: "What percentage earns each grade. Every predicted grade is read through these.",
    icon: Ruler,
  },
  {
    to: "/tutor/mistake-categories",
    label: "Mistake categories",
    hint: "The words you use for what went wrong, per subject. Marking tags against these.",
    icon: Tags,
  },
  {
    to: "/tutor/preferences",
    label: "Preferences",
    hint: "How much each kind of evidence counts towards readiness.",
    icon: SlidersHorizontal,
  },
  {
    to: "/tutor/settings",
    label: "Settings",
    hint: "Time zones, and the criteria you score students on by hand.",
    icon: SettingsIcon,
  },
];

/** One shelf entry. Every card shares the same hover (a raised row) and the
 *  same keyboard focus ring, so the grid reads as one set of doors. */
function ShelfCard({ item }: { item: Shelf }) {
  return (
    <Link
      to={item.to}
      className="group flex h-full items-start gap-3 rounded-xl border border-line bg-surface p-4 transition-colors hover:bg-surface-muted"
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
        <item.icon aria-hidden className="h-[18px] w-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-ink-900 transition-colors group-hover:text-brand-600">
          {item.label}
        </span>
        <span className="mt-0.5 block text-sm leading-relaxed text-ink-500">{item.hint}</span>
      </span>
      <ChevronRight
        aria-hidden
        className="mt-0.5 h-4 w-4 shrink-0 text-ink-500 transition-transform group-hover:translate-x-0.5 group-hover:text-brand-600"
      />
    </Link>
  );
}

function ShelfSection({
  title,
  description,
  items,
}: {
  title: string;
  description: string;
  items: Shelf[];
}) {
  return (
    <section className="space-y-3">
      <SectionHeader title={title} description={description} />
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <ShelfCard key={item.to} item={item} />
        ))}
      </div>
    </section>
  );
}

export default function LibraryPage() {
  return (
    <div>
      <PageHeader
        title="Library"
        description="Your teaching material and the settings behind marking and readiness, all in one place."
      />
      <div className="space-y-8">
        <ShelfSection
          title="Content"
          description="What your students sit and study."
          items={CONTENT}
        />
        <ShelfSection
          title="Account"
          description="How marking, grades and readiness work for you."
          items={SETTINGS}
        />
      </div>
    </div>
  );
}
