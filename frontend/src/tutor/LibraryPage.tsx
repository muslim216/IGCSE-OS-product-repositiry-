import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { classifiedFilePath, classifiedMarkSchemePath, listClassifieds } from "../api/homework";
import type { Classified } from "../api/homework";
import { listSubjects } from "../api/groups";
import {
  isSafeHttpUrl,
  listMyResources,
  resourceFilePath,
  type LibraryResource,
} from "../api/resources";
import { listChapters } from "../api/syllabus";
import { AuthFileLink } from "../components/AuthFile";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";

/**
 * Library is the tutor's teaching material, kept in one place as a record: the
 * classifieds homework is built from, and the files and recordings shared with
 * classes. It held eleven entries (papers, mocks, readiness, five setup pages,
 * settings) until the coherence pass: the owner liked how Classes is set up but
 * not that major parts of the app were "just thrown into Library". Those have
 * their own homes (Papers & mocks, Readiness, Settings).
 *
 * Syllabuses moved to Subject setup (9.3a), leaving the shelf with one card that
 * only pointed there. The owner then decided (5 Oct 2026, 9.3b) that Library is
 * filled with the classifieds and the shared files and recordings, and that
 * settings and syllabus setup stay out of it. So this page only reads: adding
 * and removing stay where they are (a classified from "Set homework", a file or
 * recording from the class's Resources tab), and a sentence under the header points
 * at where syllabuses went so nobody who remembers them here is stranded.
 *
 * Each section is its own query, so one failing shows its own error with a retry
 * and leaves the others on screen. `Shelf` and `ShelfSection` stay exported for
 * Papers & mocks, which is still a shelf of doors.
 */
export interface Shelf {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
}

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

const shortDate = (iso: string) => new Date(iso).toLocaleDateString();

const linkClass = "font-medium text-brand-600 hover:text-brand-700";

/** What a section shows while it loads, when it fails, and when it is empty —
 *  three different states, never one blank box. */
function SectionBody<T>({
  query,
  loadingLabel,
  empty,
  children,
}: {
  query: {
    isLoading: boolean;
    isError: boolean;
    error: unknown;
    data: T[] | undefined;
    refetch: () => unknown;
  };
  loadingLabel: string;
  empty: React.ReactNode;
  children: (rows: T[]) => React.ReactNode;
}) {
  if (query.isLoading) return <SectionSkeleton rows={3} label={loadingLabel} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (!query.data || query.data.length === 0) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

function ClassifiedRow({ c }: { c: Classified }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
      <span className="min-w-0">
        <span className="block truncate text-ink-900">{c.title}</span>
        <span className="block text-xs text-ink-500">Added {shortDate(c.created_at)}</span>
      </span>
      <span className="flex items-center gap-4">
        <AuthFileLink path={classifiedFilePath(c.id)} label="Open questions" />
        {c.mark_scheme_name && (
          <AuthFileLink path={classifiedMarkSchemePath(c.id)} label="Open mark scheme" />
        )}
      </span>
    </li>
  );
}

/** One subject's classifieds, filed by chapter in teaching order. The chapter
 *  names are one request for the subject, not one per row; if it fails or the
 *  subject has no extracted chapters the classifieds still list, unfiled,
 *  rather than inventing a chapter (PROD-2). */
function SubjectClassifieds({
  subjectId,
  subjectName,
  rows,
}: {
  subjectId: number;
  subjectName: string;
  rows: Classified[];
}) {
  const chapters = useQuery({
    queryKey: ["chapters", subjectId],
    queryFn: () => listChapters(subjectId),
  });
  const known = chapters.data ?? [];
  const groups = known
    .map((ch) => ({
      key: ch.id,
      label: `${ch.code} ${ch.title}`,
      rows: rows.filter((c) => c.chapter_id === ch.id),
    }))
    .filter((g) => g.rows.length > 0);
  const filed = new Set(groups.flatMap((g) => g.rows.map((c) => c.id)));
  const rest = rows.filter((c) => !filed.has(c.id));
  if (rest.length > 0) {
    groups.push({
      key: 0,
      label: groups.length > 0 ? "No chapter set" : "",
      rows: rest,
    });
  }

  return (
    <div>
      <h3 className="font-medium text-ink-900">{subjectName}</h3>
      {groups.map((g) => (
        <div key={g.key} className="mt-2">
          {g.label && <p className="text-xs font-medium text-ink-500">{g.label}</p>}
          <ul className="divide-y divide-line text-sm">
            {g.rows.map((c) => (
              <ClassifiedRow key={c.id} c={c} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function ClassifiedsSection() {
  const classifieds = useQuery({
    queryKey: ["classifieds", "library"],
    queryFn: () => listClassifieds(),
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });

  return (
    <SectionCard>
      <SectionHeader
        level="h2"
        title="Classifieds"
        description="The chapter question sets your homework is built from."
      />
      <div className="mt-3">
        <SectionBody
          query={classifieds}
          loadingLabel="Loading classifieds"
          empty={
            <EmptyState
              title="No classifieds yet."
              hint="A classified is added when you set homework from a class, by uploading its questions."
              action={
                <Link to="/tutor/classes" className={linkClass}>
                  Choose a class to set homework
                </Link>
              }
            />
          }
        >
          {(rows) => {
            const bySubject = new Map<number, Classified[]>();
            for (const c of rows)
              bySubject.set(c.subject_id, [...(bySubject.get(c.subject_id) ?? []), c]);
            return (
              <div className="space-y-5">
                {[...bySubject.entries()].map(([subjectId, list]) => (
                  <SubjectClassifieds
                    key={subjectId}
                    subjectId={subjectId}
                    subjectName={subjects.data?.find((s) => s.id === subjectId)?.name ?? "Subject"}
                    rows={list}
                  />
                ))}
              </div>
            );
          }}
        </SectionBody>
      </div>
    </SectionCard>
  );
}

function ResourceRow({ r }: { r: LibraryResource }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
      <span className="min-w-0">
        <span className="block truncate text-ink-900">{r.title}</span>
        <span className="block text-xs text-ink-500">Shared {shortDate(r.created_at)}</span>
      </span>
      {r.kind === "file" ? (
        <AuthFileLink path={resourceFilePath(r.id)} label="Open" />
      ) : (
        isSafeHttpUrl(r.url) && (
          <a href={r.url} target="_blank" rel="noreferrer noopener" className={linkClass}>
            Watch
          </a>
        )
      )}
    </li>
  );
}

/** Material grouped by class, in the order the server returned it (newest
 *  first), so a class appears where its latest item falls. */
function ByClass({ rows }: { rows: LibraryResource[] }) {
  const byClass = new Map<number, { name: string; rows: LibraryResource[] }>();
  for (const r of rows) {
    const entry = byClass.get(r.group_id) ?? { name: r.group_name, rows: [] };
    entry.rows.push(r);
    byClass.set(r.group_id, entry);
  }
  return (
    <div className="space-y-5">
      {[...byClass.entries()].map(([groupId, g]) => (
        <div key={groupId}>
          <h3 className="font-medium text-ink-900">
            <Link to={`/tutor/groups/${groupId}/resources`} className={linkClass}>
              {g.name}
            </Link>
          </h3>
          <ul className="divide-y divide-line text-sm">
            {g.rows.map((r) => (
              <ResourceRow key={r.id} r={r} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function ResourcesSection({
  kind,
  title,
  description,
  loadingLabel,
  emptyTitle,
}: {
  kind: "file" | "recording";
  title: string;
  description: string;
  loadingLabel: string;
  emptyTitle: string;
}) {
  const resources = useQuery({
    queryKey: ["resources", "library", kind],
    queryFn: () => listMyResources(kind),
  });
  return (
    <SectionCard>
      <SectionHeader level="h2" title={title} description={description} />
      <div className="mt-3">
        <SectionBody
          query={resources}
          loadingLabel={loadingLabel}
          empty={
            <EmptyState
              title={emptyTitle}
              hint="Add one from a class's Resources tab."
              action={
                <Link to="/tutor/classes" className={linkClass}>
                  Choose a class
                </Link>
              }
            />
          }
        >
          {(rows) => <ByClass rows={rows} />}
        </SectionBody>
      </div>
    </SectionCard>
  );
}

export default function LibraryPage() {
  return (
    <div>
      <PageHeader
        title="Library"
        description="Your teaching material in one place: the classifieds homework is built from, and the files and recordings you have shared with classes."
      />
      <p className="mb-6 text-sm text-ink-500">
        Looking for syllabuses? They now live in{" "}
        <Link to="/tutor/subject-setup#syllabus" className={linkClass}>
          Subject setup
        </Link>
        .
      </p>
      <div className="space-y-6">
        <ClassifiedsSection />
        <ResourcesSection
          kind="file"
          title="Files"
          description="Shared with every student in the class."
          loadingLabel="Loading files"
          emptyTitle="No files shared yet."
        />
        <ResourcesSection
          kind="recording"
          title="Recordings"
          description="Lesson recording links shared with a class."
          loadingLabel="Loading recordings"
          emptyTitle="No recordings shared yet."
        />
      </div>
    </div>
  );
}
