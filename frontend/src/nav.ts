import {
  BookOpen,
  ClipboardCheck,
  ClipboardList,
  FileText,
  FolderOpen,
  Gauge,
  GraduationCap,
  LayoutDashboard,
  PenLine,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Home as HomeIcon,
  UserRound,
  Users,
  Video,
} from "lucide-react";
import type { NavItem } from "./components/AppShell";

export const STUDENT_NAV: NavItem[] = [
  { to: "/student", label: "Home", icon: HomeIcon },
  // "Progress", not "Readiness": the destination shows a student their predicted
  // grade beside the average of their marked work and explains the gap. Naming
  // it after the engine that computes one of those numbers described the
  // machinery rather than what the reader gets (UX-25).
  { to: "/student/progress", label: "Progress", icon: Gauge },
  { to: "/student/homework", label: "Homework", icon: ClipboardList },
  { to: "/student/past-papers", label: "Past papers", icon: FileText },
  { to: "/student/mocks", label: "Mocks", icon: ClipboardCheck },
  { to: "/student/exams", label: "Exams", icon: GraduationCap },
  { to: "/student/files", label: "Files", icon: FolderOpen },
  { to: "/student/recordings", label: "Recordings", icon: Video },
];

/** A student sitting a timed paper sees only the paper, with a way out. */
export const STUDENT_SITTINGS = [
  { match: /^\/student\/mocks\/[^/]+\/?$/, leaveTo: "/student/mocks" },
  { match: /^\/student\/past-papers\/[^/]+\/?$/, leaveTo: "/student/past-papers" },
];

// Six destinations, in the order the owner set on 2026-11-08 (T-039, calm
// interface rules UX-37): Today, Mark, Classes, Students, Mocks, Library. The
// history that shaped this list, because it explains why it is short now:
// 2026-10-05 nine items ("don't change the full structure ... only the
// skeletons"), 2026-10-06 twelve (9.3c added the cross-class Homework and
// Students lists, split Mocks from Past papers, and renamed Today to Overview).
// T-039 undoes the sprawl without losing a page. Homework, Past papers,
// Readiness and Reports are things you do *to a class*, so they now sit
// inside each class as tabs (Work, Progress); a tutor looks for them there,
// not in a second list across every class. Subject setup and Settings moved
// under the tutor's name (TUTOR_ACCOUNT_MENU) because they are visited rarely.
// Labels are plain words (UX-58): the route for Today is still /tutor and for
// Mark still /tutor/review; only the label changed.
// Old URLs still land (App.tsx redirects them into the class they belong to,
// and the setup pages into Subject setup), so no bookmark 404s (edge case 20).
// `also` keeps a nested page's parent lit: Mark claims a submission's page
// (`/tutor/submissions/:id`), which is opened from the queue; Classes claims
// everything that lives inside a class (`/tutor/groups/:id/...`), a homework
// page (`/tutor/assignments/:id`) and the past-paper pages that now hang off a
// class's Work tab; Mocks and Students claim their own prefix because the exact match
// alone would drop them on a mock's or a student's page (`/tutor/mocks/:id`,
// `/tutor/students/:id`).
export const TUTOR_NAV: NavItem[] = [
  { to: "/tutor", label: "Today", icon: LayoutDashboard },
  { to: "/tutor/review", label: "Mark", icon: ClipboardCheck, also: ["/tutor/submissions"] },
  {
    to: "/tutor/classes",
    label: "Classes",
    icon: Users,
    also: ["/tutor/groups", "/tutor/assignments", "/tutor/past-papers"],
  },
  { to: "/tutor/students", label: "Students", icon: UserRound, also: ["/tutor/students"] },
  { to: "/tutor/mocks", label: "Mocks", icon: PenLine, also: ["/tutor/mocks"] },
  { to: "/tutor/library", label: "Library", icon: BookOpen },
];

/** The tutor's name menu. Subject setup claims the old setup URLs so it stays
    lit if one is ever rendered without redirecting. Sign out is added by the
    menu itself. */
export const TUTOR_ACCOUNT_MENU: NavItem[] = [
  {
    to: "/tutor/subject-setup",
    label: "Subject setup",
    icon: SlidersHorizontal,
    also: [
      "/tutor/syllabuses",
      "/tutor/boundaries",
      "/tutor/teaching-guidance",
      "/tutor/marking-rules",
      "/tutor/mistake-categories",
      "/tutor/preferences",
    ],
  },
  { to: "/tutor/settings", label: "Settings", icon: SettingsIcon },
];
