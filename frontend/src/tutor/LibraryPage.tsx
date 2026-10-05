import { Link } from "react-router-dom";
import { BookOpen, ChevronRight, type LucideIcon } from "lucide-react";
import { PageHeader } from "../components/page";
import { SectionHeader } from "../components/ui";

/**
 * Library is the tutor's source material, today the syllabuses. It held eleven
 * entries (papers, mocks, readiness, five setup pages, settings) until the
 * coherence pass: the owner liked how Classes is set up but not that major
 * parts of the app were "just thrown into Library". Those now have their own
 * homes (Papers & mocks, Readiness, Settings); this shelf is what remains.
 * It stays a shelf so new material kinds slot in as cards.
 *
 * Syllabuses are now managed in Subject setup (9.3a), so the one card is a door
 * to that section rather than a page of its own. What Library holds next is an
 * open owner decision, so the page and its nav item are left as they are.
 */
export interface Shelf {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
}

const MATERIAL: Shelf[] = [
  {
    to: "/tutor/subject-setup#syllabus",
    label: "Syllabuses",
    hint: "Upload a syllabus to build its topic tree.",
    icon: BookOpen,
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
      <ChevronRight aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-500" />
    </Link>
  );
}

export function ShelfSection({
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
        description="Your source material. Papers and mocks, readiness and settings each have their own place in the sidebar."
      />
      <div className="space-y-8">
        <ShelfSection
          title="Material"
          description="What the topic tree and your teaching are built from."
          items={MATERIAL}
        />
      </div>
    </div>
  );
}
