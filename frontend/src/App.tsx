import { Navigate, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  ClipboardCheck,
  ClipboardList,
  FileText,
  FolderOpen,
  FileBarChart,
  Gauge,
  GraduationCap,
  Settings as SettingsIcon,
  Home as HomeIcon,
  Sunrise,
  Users,
  Video,
} from "lucide-react";
import { useAuth } from "./auth/AuthContext";
import type { NavItem } from "./components/AppShell";
import LoginPage from "./auth/LoginPage";
import TutorSignupPage from "./auth/TutorSignupPage";
import JoinPage from "./auth/JoinPage";
import ParentJoinPage from "./auth/ParentJoinPage";
import { homePathFor, ProtectedRoute } from "./auth/ProtectedRoute";
import AppShell from "./components/AppShell";
import LandingPage from "./marketing/LandingPage";
import PrivacyPolicyPage from "./legal/PrivacyPolicyPage";
import { NotFoundPage } from "./components/page";
import { BrandedLoading } from "./components/brand";
import GroupsPage from "./tutor/GroupsPage";
import GroupLayout from "./tutor/GroupLayout";
import HomeworkTab from "./tutor/tabs/HomeworkTab";
import StudentsTab from "./tutor/tabs/StudentsTab";
import ScheduleTab from "./tutor/tabs/ScheduleTab";
import SyllabusTab from "./tutor/tabs/SyllabusTab";
import ResourcesTab from "./tutor/tabs/ResourcesTab";
import AssignmentCreatePage from "./tutor/AssignmentCreatePage";
import AssignmentDetailPage from "./tutor/AssignmentDetailPage";
import SubmissionReviewPage from "./tutor/SubmissionReviewPage";
import StudentDetailPage from "./tutor/StudentDetailPage";
import GroupAnalyticsPage from "./tutor/GroupAnalyticsPage";
import MockEntryPage from "./tutor/MockEntryPage";
import ClassReadinessPage from "./tutor/ClassReadinessPage";
import ReportsPage from "./tutor/ReportsPage";
import ClassReportPage from "./tutor/ClassReportPage";
import TodayDashboard from "./tutor/today/TodayDashboard";
import ReviewQueuePage from "./tutor/ReviewQueuePage";
import LibraryPage from "./tutor/LibraryPage";
import PapersHubPage from "./tutor/PapersHubPage";
import MocksPage from "./tutor/MocksPage";
import SyllabusUploadPage from "./tutor/SyllabusUploadPage";
import SettingsPage from "./tutor/SettingsPage";
import IntegrationCallbackPage from "./tutor/IntegrationCallbackPage";
import TutorPastPapersPage from "./tutor/PastPapersPage";
import BookletsPage from "./tutor/BookletsPage";

import StudentHomePage from "./student/StudentHomePage";
import ProgressPage from "./student/ProgressPage";
import WelcomePage from "./student/WelcomePage";
import HomeworkPage from "./student/HomeworkPage";
import SubmitHomeworkPage from "./student/SubmitHomeworkPage";
import FilesPage from "./student/FilesPage";
import RecordingsPage from "./student/RecordingsPage";
import ExamsPage from "./student/ExamsPage";
import StudentPastPapersPage from "./student/PastPapersPage";
import SitPastPaperPage from "./student/SitPastPaperPage";
import StudentMocksPage from "./student/MocksPage";
import SitMockPage from "./student/SitMockPage";
import ParentDashboard from "./parent/ParentDashboard";
import AccountPage from "./components/AccountPage";

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <BrandedLoading />;
  // Signed out, show what the product is rather than bouncing to a login form.
  return user ? <Navigate to={homePathFor(user)} replace /> : <LandingPage />;
}

const STUDENT_NAV: NavItem[] = [
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

// Eight destinations, set by the owner (2026-10-05): "don't change the full
// structure ... only the skeletons". Classes was right; the trouble was that
// readiness, exam papers and every setup page had been dropped onto the Library
// shelf. Each now has a name where the tutor looks for it: Readiness and
// Papers & mocks are the work, Library is source material, Settings is where
// marking, grades and the account are configured. The daily loop stays first.
// Old URLs still land (setup pages redirect into Settings), so no bookmark
// 404s (edge case 20). `also` keeps a nested page's parent lit.
const TUTOR_NAV: NavItem[] = [
  { to: "/tutor", label: "Today", icon: Sunrise },
  { to: "/tutor/classes", label: "Classes", icon: Users, also: ["/tutor/groups"] },
  { to: "/tutor/review", label: "Review", icon: ClipboardCheck },
  { to: "/tutor/readiness", label: "Readiness", icon: Gauge },
  { to: "/tutor/reports", label: "Reports", icon: FileBarChart },
  {
    to: "/tutor/papers",
    label: "Papers & mocks",
    icon: FileText,
    also: ["/tutor/past-papers", "/tutor/booklets", "/tutor/mocks"],
  },
  { to: "/tutor/library", label: "Library", icon: BookOpen, also: ["/tutor/syllabuses"] },
  { to: "/tutor/settings", label: "Settings", icon: SettingsIcon },
];

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/privacy" element={<PrivacyPolicyPage />} />
      <Route path="/signup" element={<TutorSignupPage />} />
      <Route path="/join/:code" element={<JoinPage />} />
      <Route path="/parent-join/:code" element={<ParentJoinPage />} />

      <Route element={<ProtectedRoute roles={["tutor", "admin"]} />}>
        <Route element={<AppShell title="Tutor" nav={TUTOR_NAV} accountPath="/tutor/settings" />}>
          <Route path="/tutor" element={<TodayDashboard />} />
          <Route path="/tutor/classes" element={<GroupsPage />} />
          <Route path="/tutor/review" element={<ReviewQueuePage />} />
          <Route path="/tutor/library" element={<LibraryPage />} />
          <Route path="/tutor/papers" element={<PapersHubPage />} />
          {/* Setup pages became sections of Settings; the old URLs land on theirs. */}
          <Route path="/tutor/readiness" element={<ClassReadinessPage />} />
          <Route path="/tutor/reports" element={<ReportsPage />} />
          <Route path="/tutor/reports/:groupId" element={<ClassReportPage />} />
          <Route
            path="/tutor/boundaries"
            element={<Navigate to="/tutor/settings#boundaries" replace />}
          />
          <Route
            path="/tutor/mistake-categories"
            element={<Navigate to="/tutor/settings#mistake-categories" replace />}
          />
          <Route path="/tutor/syllabuses" element={<SyllabusUploadPage />} />
          <Route
            path="/tutor/teaching-guidance"
            element={<Navigate to="/tutor/settings#teaching-guidance" replace />}
          />
          <Route
            path="/tutor/marking-rules"
            element={<Navigate to="/tutor/settings#marking-rules" replace />}
          />
          <Route
            path="/tutor/preferences"
            element={<Navigate to="/tutor/settings#preferences" replace />}
          />
          <Route path="/tutor/mocks" element={<MocksPage />} />
          <Route path="/tutor/today" element={<Navigate to="/tutor" replace />} />
          {/* Homework overview folded into Review; the old bookmark still lands. */}
          <Route path="/tutor/homework" element={<Navigate to="/tutor/review" replace />} />
          {/* Everything belonging to a class renders inside its tabbed layout. */}
          <Route path="/tutor/groups/:groupId" element={<GroupLayout />}>
            <Route index element={<Navigate to="homework" replace />} />
            <Route path="homework" element={<HomeworkTab />} />
            <Route path="students" element={<StudentsTab />} />
            <Route path="syllabus" element={<SyllabusTab />} />
            <Route path="schedule" element={<ScheduleTab />} />
            <Route path="resources" element={<ResourcesTab />} />
            <Route path="analytics" element={<GroupAnalyticsPage />} />
            <Route path="new-homework" element={<AssignmentCreatePage />} />
            <Route path="mock" element={<MockEntryPage />} />
          </Route>
          <Route path="/tutor/assignments/:assignmentId" element={<AssignmentDetailPage />} />
          <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
          <Route path="/tutor/settings" element={<SettingsPage />} />
          <Route
            path="/tutor/settings/integrations/:provider/callback"
            element={<IntegrationCallbackPage />}
          />
          <Route path="/tutor/past-papers" element={<TutorPastPapersPage />} />
          <Route path="/tutor/booklets" element={<BookletsPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route
          element={<AppShell title="Student" nav={STUDENT_NAV} accountPath="/student/account" />}
        >
          <Route path="/student" element={<StudentHomePage />} />
          <Route path="/student/welcome" element={<WelcomePage />} />
          <Route path="/student/progress" element={<ProgressPage />} />
          {/* Deleted in 0.4 (AV-100). The old URL lands on Progress rather
              than 404ing a bookmark. */}
          <Route
            path="/student/improvement"
            element={<Navigate to="/student/progress" replace />}
          />
          {/* The old Readiness page's URL still lands — no bookmark 404s. */}
          <Route path="/student/readiness" element={<Navigate to="/student/progress" replace />} />
          <Route path="/student/files" element={<FilesPage />} />
          <Route path="/student/recordings" element={<RecordingsPage />} />
          <Route path="/student/homework" element={<HomeworkPage />} />
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
          {/* Deleted in 0.3 (AV-57). The old URL lands on Home. */}
          <Route path="/student/tutor" element={<Navigate to="/student" replace />} />
          <Route path="/student/past-papers" element={<StudentPastPapersPage />} />
          <Route path="/student/past-papers/:pastPaperId" element={<SitPastPaperPage />} />
          <Route path="/student/mocks" element={<StudentMocksPage />} />
          <Route path="/student/mocks/:mockId" element={<SitMockPage />} />
          <Route path="/student/exams" element={<ExamsPage />} />
          <Route path="/student/account" element={<AccountPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["parent"]} />}>
        <Route element={<AppShell title="Parent" accountPath="/parent/account" />}>
          <Route path="/parent" element={<ParentDashboard />} />
          <Route path="/parent/account" element={<AccountPage />} />
        </Route>
      </Route>

      {/* A real 404, not a silent bounce to "/": a mistyped link should say so. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
