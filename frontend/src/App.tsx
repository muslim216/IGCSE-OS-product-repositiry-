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
import StudentDashboard from "./student/StudentDashboard";
import HomeworkPage from "./student/HomeworkPage";
import SubmitHomeworkPage from "./student/SubmitHomeworkPage";
import ParentDashboard from "./parent/ParentDashboard";

function Home() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
  return <Navigate to={user ? homePathFor(user) : "/login"} replace />;
}

const STUDENT_NAV = [
  { to: "/student", label: "Dashboard" },
  { to: "/student/homework", label: "Homework" },
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
        <Route element={<AppShell title="Tutor" />}>
          <Route path="/tutor" element={<GroupsPage />} />
          <Route path="/tutor/groups/:groupId" element={<GroupDetailPage />} />
          <Route path="/tutor/groups/:groupId/new-homework" element={<AssignmentCreatePage />} />
          <Route path="/tutor/groups/:groupId/analytics" element={<GroupAnalyticsPage />} />
          <Route path="/tutor/groups/:groupId/mock" element={<MockEntryPage />} />
          <Route path="/tutor/assignments/:assignmentId" element={<AssignmentDetailPage />} />
          <Route path="/tutor/submissions/:submissionId" element={<SubmissionReviewPage />} />
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route element={<AppShell title="Student" nav={STUDENT_NAV} />}>
          <Route path="/student" element={<StudentDashboard />} />
          <Route path="/student/homework" element={<HomeworkPage />} />
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
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
