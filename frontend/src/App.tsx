import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import TutorSignupPage from "./auth/TutorSignupPage";
import JoinPage from "./auth/JoinPage";
import ParentJoinPage from "./auth/ParentJoinPage";
import { homePathFor, ProtectedRoute } from "./auth/ProtectedRoute";
import AppShell from "./components/AppShell";
import LandingPage from "./marketing/LandingPage";
import GroupsPage from "./tutor/GroupsPage";
import ReviewQueuePage from "./tutor/ReviewQueuePage";
import GroupLayout from "./tutor/GroupLayout";
import HomeworkTab from "./tutor/tabs/HomeworkTab";
import StudentsTab from "./tutor/tabs/StudentsTab";
import SyllabusTab from "./tutor/tabs/SyllabusTab";
import ScheduleTab from "./tutor/tabs/ScheduleTab";
import AnalyticsTab from "./tutor/tabs/AnalyticsTab";
import {
  LegacyAssignmentRedirect,
  LegacyStudentRedirect,
  LegacySubmissionRedirect,
} from "./tutor/LegacyRedirects";
import AssignmentCreatePage from "./tutor/AssignmentCreatePage";
import AssignmentDetailPage from "./tutor/AssignmentDetailPage";
import SubmissionReviewPage from "./tutor/SubmissionReviewPage";
import StudentDetailPage from "./tutor/StudentDetailPage";
import MockEntryPage from "./tutor/MockEntryPage";
import StudentDashboard from "./student/StudentDashboard";
import HomeworkPage from "./student/HomeworkPage";
import SubmitHomeworkPage from "./student/SubmitHomeworkPage";
import TutorChatPage from "./student/TutorChatPage";
import ParentDashboard from "./parent/ParentDashboard";

function Home() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
  // Signed out, show what the product is rather than bouncing to a login form.
  return user ? <Navigate to={homePathFor(user)} replace /> : <LandingPage />;
}

const TUTOR_NAV = [
  { to: "/tutor", label: "Classes", exact: true },
  { to: "/tutor/review", label: "Needs review" },
];
const STUDENT_NAV = [
  { to: "/student", label: "Dashboard", exact: true },
  { to: "/student/homework", label: "Homework" },
  { to: "/student/tutor", label: "AI Tutor" },
];
const PARENT_NAV = [{ to: "/parent", label: "Overview" }];

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
          <Route path="/tutor" element={<GroupsPage />} />
          <Route path="/tutor/review" element={<ReviewQueuePage />} />

          {/* Everything belonging to a class lives inside it. */}
          <Route path="/tutor/groups/:groupId" element={<GroupLayout />}>
            <Route index element={<Navigate to="homework" replace />} />
            <Route path="homework" element={<HomeworkTab />} />
            <Route path="students" element={<StudentsTab />} />
            <Route path="syllabus" element={<SyllabusTab />} />
            <Route path="schedule" element={<ScheduleTab />} />
            <Route path="analytics" element={<AnalyticsTab />} />
            <Route path="homework/new" element={<AssignmentCreatePage />} />
            <Route path="homework/:assignmentId" element={<AssignmentDetailPage />} />
            <Route path="submissions/:submissionId" element={<SubmissionReviewPage />} />
            <Route path="students/:studentId" element={<StudentDetailPage />} />
            <Route path="mock" element={<MockEntryPage />} />
          </Route>

          {/* Pre-restructure URLs — resolve the class, then hand off. */}
          <Route
            path="/tutor/groups/:groupId/new-homework"
            element={<Navigate to="../homework/new" replace relative="path" />}
          />
          <Route path="/tutor/assignments/:assignmentId" element={<LegacyAssignmentRedirect />} />
          <Route path="/tutor/submissions/:submissionId" element={<LegacySubmissionRedirect />} />
          <Route path="/tutor/students/:studentId" element={<LegacyStudentRedirect />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route element={<AppShell title="Student" nav={STUDENT_NAV} />}>
          <Route path="/student" element={<StudentDashboard />} />
          <Route path="/student/homework" element={<HomeworkPage />} />
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
          <Route path="/student/tutor" element={<TutorChatPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["parent"]} />}>
        <Route element={<AppShell title="Parent" nav={PARENT_NAV} />}>
          <Route path="/parent" element={<ParentDashboard />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
