import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import TutorSignupPage from "./auth/TutorSignupPage";
import JoinPage from "./auth/JoinPage";
import ParentJoinPage from "./auth/ParentJoinPage";
import { homePathFor, ProtectedRoute } from "./auth/ProtectedRoute";
import AppShell from "./components/AppShell";
import GroupsPage from "./tutor/GroupsPage";
import GroupDetailPage from "./tutor/GroupDetailPage";
import AssignmentCreatePage from "./tutor/AssignmentCreatePage";
import AssignmentDetailPage from "./tutor/AssignmentDetailPage";
import SubmissionReviewPage from "./tutor/SubmissionReviewPage";
import StudentDetailPage from "./tutor/StudentDetailPage";
import GroupAnalyticsPage from "./tutor/GroupAnalyticsPage";
import MockEntryPage from "./tutor/MockEntryPage";
import ClassReadinessPage from "./tutor/ClassReadinessPage";
import HomeworkOverviewPage from "./tutor/HomeworkOverviewPage";
import PreferencesPage from "./tutor/PreferencesPage";
import TodayPage from "./tutor/TodayPage";
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
import TutorHomePage from "./tutor/TutorHomePage";
import ParentDashboard from "./parent/ParentDashboard";

function Home() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
  return <Navigate to={user ? homePathFor(user) : "/login"} replace />;
}

const STUDENT_NAV = [
  { to: "/student", label: "Home" },
  { to: "/student/readiness", label: "Readiness" },
  { to: "/student/files", label: "Files" },
  { to: "/student/recordings", label: "Recordings" },
  { to: "/student/homework", label: "Homework" },
  { to: "/student/tutor", label: "AI Tutor" },
  { to: "/student/past-papers", label: "Past papers" },
  { to: "/student/exams", label: "Exams" },
];

const TUTOR_NAV = [
  { to: "/tutor", label: "Home" },
  { to: "/tutor/classes", label: "Classes" },
  { to: "/tutor/readiness", label: "Class readiness" },
  { to: "/tutor/homework", label: "Homework" },
  { to: "/tutor/syllabuses", label: "Syllabuses" },
  { to: "/tutor/preferences", label: "Preferences" },
  { to: "/tutor/mocks", label: "Mocks" },
  { to: "/tutor/past-papers", label: "Past papers" },
  { to: "/tutor/today", label: "Today" },
  { to: "/tutor/settings", label: "Settings" },
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
          <Route path="/tutor" element={<TutorHomePage />} />
          <Route path="/tutor/classes" element={<GroupsPage />} />
          <Route path="/tutor/readiness" element={<ClassReadinessPage />} />
          <Route path="/tutor/homework" element={<HomeworkOverviewPage />} />
          <Route path="/tutor/syllabuses" element={<SyllabusUploadPage />} />
          <Route path="/tutor/preferences" element={<PreferencesPage />} />
          <Route path="/tutor/mocks" element={<MocksPage />} />
          <Route path="/tutor/today" element={<TodayPage />} />
          <Route path="/tutor/groups/:groupId" element={<GroupDetailPage />} />
          <Route path="/tutor/groups/:groupId/new-homework" element={<AssignmentCreatePage />} />
          <Route path="/tutor/groups/:groupId/analytics" element={<GroupAnalyticsPage />} />
          <Route path="/tutor/groups/:groupId/mock" element={<MockEntryPage />} />
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
