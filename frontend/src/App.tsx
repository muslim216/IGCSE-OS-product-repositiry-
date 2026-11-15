import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { STUDENT_NAV, STUDENT_SITTINGS, TUTOR_ACCOUNT_MENU, TUTOR_NAV } from "./nav";
import { Keep, MovedToClass, ReportRedirect } from "./redirects";
import LoginPage from "./auth/LoginPage";
import TutorSignupPage from "./auth/TutorSignupPage";
import JoinPage from "./auth/JoinPage";
import ParentJoinPage from "./auth/ParentJoinPage";
import { homePathFor, ProtectedRoute } from "./auth/ProtectedRoute";
import AppShell from "./components/AppShell";
import LandingPage from "./marketing/LandingPage";
import PrivacyPolicyPage from "./legal/PrivacyPolicyPage";
import { NotFoundPage } from "./components/page";
import WeeklySendPage, { WeeklySendRedirect } from "./components/WeeklySendPage";
import { BrandedLoading } from "./components/brand";
import GroupsPage from "./tutor/GroupsPage";
import GroupLayout from "./tutor/GroupLayout";
import TutorStudentsPage from "./tutor/StudentsPage";
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
import TodayDashboard from "./tutor/today/TodayDashboard";
import ReviewQueuePage from "./tutor/ReviewQueuePage";
import LibraryPage from "./tutor/LibraryPage";
import MockPage from "./tutor/MockPage";
import MocksPage from "./tutor/MocksPage";
import SubjectSetupPage from "./tutor/SubjectSetupPage";
import SettingsPage from "./tutor/SettingsPage";
import IntegrationCallbackPage from "./tutor/IntegrationCallbackPage";
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

const PastPapersMoved = () => (
  <MovedToClass tab="homework" hash="#past-papers" tip="Past papers now live inside each class." />
);

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
        <Route element={<AppShell
            title="Tutor"
            nav={TUTOR_NAV}
            accountPath="/tutor/settings"
            accountMenu={TUTOR_ACCOUNT_MENU}
          />}>
          <Route path="/tutor" element={<TodayDashboard />} />
          <Route path="/tutor/classes" element={<GroupsPage />} />
          <Route path="/tutor/review" element={<ReviewQueuePage />} />
          <Route path="/tutor/library" element={<LibraryPage />} />
          {/* Homework, Past papers, Readiness and Reports left the menu in T-039 and live inside each class. */}
          <Route path="/tutor/papers" element={<PastPapersMoved />} />
          {/* Setup pages became sections of Subject setup (first of Settings); the old URLs land on theirs. */}
          <Route path="/tutor/subject-setup" element={<SubjectSetupPage />} />
          <Route
            path="/tutor/readiness"
            element={
              <MovedToClass
                tab="analytics"
                hash="#readiness"
                tip="Readiness now lives inside each class."
              />
            }
          />
          <Route
            path="/tutor/reports"
            element={
              <MovedToClass
                tab="analytics"
                hash="#reports"
                tip="Reports now live inside each class."
              />
            }
          />
          <Route path="/tutor/reports/:groupId" element={<ReportRedirect />} />
          <Route
            path="/tutor/boundaries"
            element={<Keep to="/tutor/subject-setup" hash="#boundaries" />}
          />
          <Route
            path="/tutor/mistake-categories"
            element={<Keep to="/tutor/subject-setup" hash="#mistake-categories" />}
          />
          <Route
            path="/tutor/syllabuses"
            element={<Keep to="/tutor/subject-setup" hash="#syllabus" />}
          />
          <Route
            path="/tutor/teaching-guidance"
            element={<Keep to="/tutor/subject-setup" hash="#teaching-guidance" />}
          />
          <Route
            path="/tutor/marking-rules"
            element={<Keep to="/tutor/subject-setup" hash="#marking-rules" />}
          />
          <Route
            path="/tutor/preferences"
            element={<Keep to="/tutor/subject-setup" hash="#preferences" />}
          />
          <Route path="/tutor/mocks" element={<MocksPage />} />
          <Route path="/tutor/mocks/:mockId" element={<MockPage />} />
          <Route path="/tutor/today" element={<Keep to="/tutor" />} />
          <Route
            path="/tutor/homework"
            element={
              <MovedToClass
                tab="homework"
                hash=""
                tip="Homework now lives inside each class."
              />
            }
          />
          <Route path="/tutor/students" element={<TutorStudentsPage />} />
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
          <Route path="/tutor/weekly/:sendId" element={<WeeklySendPage />} />
          <Route
            path="/tutor/settings/integrations/:provider/callback"
            element={<IntegrationCallbackPage />}
          />
          <Route path="/tutor/past-papers" element={<PastPapersMoved />} />
          <Route path="/tutor/booklets" element={<PastPapersMoved />} />
          <Route path="/tutor/past-papers/booklets" element={<BookletsPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route
          element={<AppShell
            title="Student"
            nav={STUDENT_NAV}
            accountPath="/student/account"
            sittings={STUDENT_SITTINGS}
          />}
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
          <Route path="/student/weekly/:sendId" element={<WeeklySendPage />} />
          <Route path="/student/account" element={<AccountPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["parent"]} />}>
        <Route element={<AppShell title="Parent" accountPath="/parent/account" />}>
          <Route path="/parent" element={<ParentDashboard />} />
          <Route path="/parent/weekly/:sendId" element={<WeeklySendPage />} />
          <Route path="/parent/account" element={<AccountPage />} />
        </Route>
      </Route>

      {/* The address a WhatsApp or email message carries: it cannot know the
          reader's role, so it forwards to the same send inside their own shell. */}
      <Route element={<ProtectedRoute roles={["tutor", "admin", "student", "parent"]} />}>
        <Route path="/weekly/:sendId" element={<WeeklySendRedirect />} />
      </Route>

      {/* A real 404, not a silent bounce to "/": a mistyped link should say so. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
