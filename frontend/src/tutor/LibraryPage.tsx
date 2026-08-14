import { Link } from "react-router-dom";
import {
  BookOpen,
  FileText,
  Gauge,
  PenLine,
  Settings as SettingsIcon,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";

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
    hint: "Browse and assign past papers by board and topic.",
    icon: FileText,
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
    to: "/tutor/readiness",
    label: "Class readiness",
    hint: "Drill into a class and flag learners who need attention.",
    icon: Gauge,
  },
];

const SETTINGS: Shelf[] = [
  {
    to: "/tutor/preferences",
    label: "Preferences",
    hint: "Tune how readiness is weighted.",
    icon: SlidersHorizontal,
  },
  {
    to: "/tutor/settings",
    label: "Settings",
    hint: "Classroom, timezone and integrations.",
    icon: SettingsIcon,
  },
];

function ShelfCard({ item }: { item: Shelf }) {
  return (
    <Link
      to={item.to}
      className="flex items-start gap-3 rounded-lg border border-line bg-surface p-4 transition hover:border-line-strong"
    >
      <item.icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
      <span>
        <span className="block font-medium text-ink-900">{item.label}</span>
        <span className="mt-0.5 block text-sm text-ink-500">{item.hint}</span>
      </span>
    </Link>
  );
}

export default function LibraryPage() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Library</h2>
        <p className="text-sm text-ink-500">Reference material, content and settings.</p>
      </div>

      <section>
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
          Content
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {CONTENT.map((item) => (
            <ShelfCard key={item.to} item={item} />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
          Account
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {SETTINGS.map((item) => (
            <ShelfCard key={item.to} item={item} />
          ))}
        </div>
      </section>
    </div>
  );
}
