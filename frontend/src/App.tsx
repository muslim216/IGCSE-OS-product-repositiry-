import { Navigate, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  ClipboardList,
  FileText,
  FolderOpen,
  Gauge,
  GraduationCap,
  Home as HomeIcon,
  PenLine,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Sparkles,
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
import HomeworkOverviewPage from "./tutor/HomeworkOverviewPage";
import PreferencesPage from "./tutor/PreferencesPage";
import TodayDashboard from "./tutor/today/TodayDashboard";
import MocksPage from "./tutor/MocksPage";
import SyllabusUploadPage from "./tutor/SyllabusUploadPage";
import ClassroomSettingsPage from "./tutor/ClassroomSettingsPage";
import ClassroomCallbackPage from "./tutor/ClassroomCallbackPage";
import TutorPastPapersPage from "./tutor/PastPapersPage";

import StudentDashboard from "./student/StudentDashboard";
import StudentHomePage from "./student/StudentHomePage";
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
  { to: "/student/readiness", label: "Readiness", icon: Gauge },
  { to: "/student/homework", label: "Homework", icon: ClipboardList },
  { to: "/student/past-papers", label: "Past papers", icon: FileText },
  { to: "/student/exams", label: "Exams", icon: GraduationCap },
  { to: "/student/files", label: "Files", icon: FolderOpen },
  { to: "/student/recordings", label: "Recordings", icon: Video },
  { to: "/student/tutor", label: "AI Tutor", icon: Sparkles, slot: "bottom" },
];

const TUTOR_NAV: NavItem[] = [
  { to: "/tutor", label: "Today", icon: Sunrise },
  { to: "/tutor/classes", label: "Classes", icon: Users },
  { to: "/tutor/readiness", label: "Class readiness", icon: Gauge },
  { to: "/tutor/homework", label: "Homework", icon: ClipboardList },
  { to: "/tutor/past-papers", label: "Past papers", icon: FileText },
  { to: "/tutor/mocks", label: "Mocks", icon: PenLine },
  { to: "/tutor/syllabuses", label: "Syllabuses", icon: BookOpen },
  { to: "/tutor/preferences", label: "Preferences", icon: SlidersHorizontal },
  { to: "/tutor/settings", label: "Settings", icon: SettingsIcon },
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
          <Route path="/tutor/readiness" element={<ClassReadinessPage />} />
          <Route path="/tutor/homework" element={<HomeworkOverviewPage />} />
          <Route path="/tutor/syllabuses" element={<SyllabusUploadPage />} />
          <Route path="/tutor/preferences" element={<PreferencesPage />} />
          <Route path="/tutor/mocks" element={<MocksPage />} />
          <Route path="/tutor/today" element={<Navigate to="/tutor" replace />} />
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
          <Route path="/tutor/settings" element={<ClassroomSettingsPage />} />
          <Route path="/tutor/past-papers" element={<TutorPastPapersPage />} />
        </Route>
        <Route
          path="/settings/classroom/callback"
          element={<ClassroomCallbackPage />}
        />
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route element={<AppShell title="Student" nav={STUDENT_NAV} />}>
          <Route path="/student" element={<StudentHomePage />} />
          <Route path="/student/readiness" element={<StudentDashboard />} />
          <Route path="/student/files" element={<FilesPage />} />
          <Route path="/student/recordings" element={<RecordingsPage />} />
          <Route path="/student/homework" element={<HomeworkPage />} />
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
          <Route path="/student/tutor" element={<TutorChatPage />} />
          <Route path="/student/past-papers" element={<StudentPastPapersPage />} />
          <Route
            path="/student/past-papers/:pastPaperId"
            element={<SitPastPaperPage />}
          />
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
