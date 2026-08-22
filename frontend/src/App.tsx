import { Navigate, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  ClipboardCheck,
  ClipboardList,
  FileText,
  FolderOpen,
  Gauge,
  GraduationCap,
  Home as HomeIcon,
  Sparkles,
  Sunrise,
  TrendingUp,
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
import PreferencesPage from "./tutor/PreferencesPage";
import GradeBoundariesPage from "./tutor/GradeBoundariesPage";
import TodayDashboard from "./tutor/today/TodayDashboard";
import ReviewQueuePage from "./tutor/ReviewQueuePage";
import LibraryPage from "./tutor/LibraryPage";
import MocksPage from "./tutor/MocksPage";
import SyllabusUploadPage from "./tutor/SyllabusUploadPage";
import SettingsPage from "./tutor/SettingsPage";
import TutorPastPapersPage from "./tutor/PastPapersPage";

import StudentHomePage from "./student/StudentHomePage";
import ProgressPage from "./student/ProgressPage";
import ImprovementPage from "./student/ImprovementPage";
import WelcomePage from "./student/WelcomePage";
import HomeworkPage from "./student/HomeworkPage";
import SubmitHomeworkPage from "./student/SubmitHomeworkPage";
import TutorChatPage from "./student/TutorChatPage";
import FilesPage from "./student/FilesPage";
import RecordingsPage from "./student/RecordingsPage";
import ExamsPage from "./student/ExamsPage";
import StudentPastPapersPage from "./student/PastPapersPage";
import SitPastPaperPage from "./student/SitPastPaperPage";
import ParentDashboard from "./parent/ParentDashboard";

function Home() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
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
  { to: "/student/improvement", label: "Improvement", icon: TrendingUp },
  { to: "/student/homework", label: "Homework", icon: ClipboardList },
  { to: "/student/past-papers", label: "Past papers", icon: FileText },
  { to: "/student/exams", label: "Exams", icon: GraduationCap },
  { to: "/student/files", label: "Files", icon: FolderOpen },
  { to: "/student/recordings", label: "Recordings", icon: Video },
  { to: "/student/tutor", label: "AI Tutor", icon: Sparkles, slot: "bottom" },
];

// Four destinations, not nine. Today · Classes · Review · Library is the whole
// daily loop; everything else (past papers, mocks, syllabuses, class readiness,
// preferences, settings) moved onto the Library shelf, still one tap away and
// still reachable by its old URL — no bookmark 404s (edge case 20).
const TUTOR_NAV: NavItem[] = [
  { to: "/tutor", label: "Today", icon: Sunrise },
  { to: "/tutor/classes", label: "Classes", icon: Users },
  { to: "/tutor/review", label: "Review", icon: ClipboardCheck },
  { to: "/tutor/library", label: "Library", icon: BookOpen },
];

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<TutorSignupPage />} />
      <Route path="/join/:code" element={<JoinPage />} />
      <Route path="/parent-join/:code" element={<ParentJoinPage />} />

      <Route element={<ProtectedRoute roles={["tutor", "admin"]} />}>
        <Route element={<AppShell title="Tutor" nav={TUTOR_NAV} />}>
          <Route path="/tutor" element={<TodayDashboard />} />
          <Route path="/tutor/classes" element={<GroupsPage />} />
          <Route path="/tutor/review" element={<ReviewQueuePage />} />
          <Route path="/tutor/library" element={<LibraryPage />} />
          <Route path="/tutor/readiness" element={<ClassReadinessPage />} />
          <Route path="/tutor/boundaries" element={<GradeBoundariesPage />} />
          <Route path="/tutor/syllabuses" element={<SyllabusUploadPage />} />
          <Route path="/tutor/preferences" element={<PreferencesPage />} />
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
          <Route path="/tutor/past-papers" element={<TutorPastPapersPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route element={<AppShell title="Student" nav={STUDENT_NAV} />}>
          <Route path="/student" element={<StudentHomePage />} />
          <Route path="/student/welcome" element={<WelcomePage />} />
          <Route path="/student/progress" element={<ProgressPage />} />
          <Route path="/student/improvement" element={<ImprovementPage />} />
          {/* The old Readiness page's URL still lands — no bookmark 404s. */}
          <Route path="/student/readiness" element={<Navigate to="/student/progress" replace />} />
          <Route path="/student/files" element={<FilesPage />} />
          <Route path="/student/recordings" element={<RecordingsPage />} />
          <Route path="/student/homework" element={<HomeworkPage />} />
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
          <Route path="/student/tutor" element={<TutorChatPage />} />
          <Route path="/student/past-papers" element={<StudentPastPapersPage />} />
          <Route path="/student/past-papers/:pastPaperId" element={<SitPastPaperPage />} />
          <Route path="/student/exams" element={<ExamsPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["parent"]} />}>
        <Route element={<AppShell title="Parent" />}>
          <Route path="/parent" element={<ParentDashboard />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
