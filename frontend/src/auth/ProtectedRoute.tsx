import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";
import type { User } from "../api/client";

export function homePathFor(user: User): string {
  switch (user.role) {
    case "tutor":
      return "/tutor";
    case "student":
      return "/student";
    case "parent":
      return "/parent";
    case "admin":
      return "/tutor";
  }
}

export function ProtectedRoute({ roles }: { roles: User["role"][] }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homePathFor(user)} replace />;
  return <Outlet />;
}
