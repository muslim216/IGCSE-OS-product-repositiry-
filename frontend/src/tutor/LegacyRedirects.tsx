import { Navigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getAssignment, getSubmission } from "../api/homework";

/*
 * Homework, submissions and students used to live at flat top-level URLs, losing
 * the class they belong to. They're now nested under their class, so these
 * resolvers keep old links and bookmarks working: look up whichever class the
 * record belongs to, then hand off to the nested route.
 */

function Resolving() {
  return <p className="text-slate-500">Loading…</p>;
}

export function LegacyAssignmentRedirect() {
  const { assignmentId } = useParams();
  const id = Number(assignmentId);
  const assignment = useQuery({
    queryKey: ["assignment", id],
    queryFn: () => getAssignment(id),
  });

  if (assignment.isLoading) return <Resolving />;
  if (!assignment.data) return <Navigate to="/tutor" replace />;
  return (
    <Navigate to={`/tutor/groups/${assignment.data.group_id}/homework/${id}`} replace />
  );
}

export function LegacySubmissionRedirect() {
  const { submissionId } = useParams();
  const id = Number(submissionId);
  const submission = useQuery({
    queryKey: ["submission", id],
    queryFn: () => getSubmission(id),
  });
  // A submission knows its assignment; the assignment knows the class.
  const assignment = useQuery({
    queryKey: ["assignment", submission.data?.assignment_id],
    queryFn: () => getAssignment(submission.data!.assignment_id),
    enabled: submission.data !== undefined,
  });

  if (submission.isLoading || assignment.isLoading) return <Resolving />;
  if (!assignment.data) return <Navigate to="/tutor" replace />;
  return (
    <Navigate to={`/tutor/groups/${assignment.data.group_id}/submissions/${id}`} replace />
  );
}

export function LegacyStudentRedirect() {
  const { studentId } = useParams();
  const [params] = useSearchParams();
  const groupId = params.get("group");
  // Old student links always carried ?group=; without it there's no class to open.
  if (!groupId) return <Navigate to="/tutor" replace />;
  return <Navigate to={`/tutor/groups/${groupId}/students/${studentId}`} replace />;
}
