import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { cn } from "../ui";

export interface NavItem {
  to: string;
  label: string;
  /**
   * Match this path exactly. Only role-root links need it — without it a nested
   * route like /student/homework/12 would leave its own tab unhighlighted.
   */
  exact?: boolean;
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();
  return (
    <div className="min-h-screen bg-surface-sunken">
      <header className="border-b border-slate-200 bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-lg font-semibold text-slate-900">IGCSE Student OS</span>
            <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs uppercase tracking-wide text-slate-500">
              {title}
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-600">{user?.name}</span>
            <button onClick={signOut} className="text-slate-500 hover:text-slate-900">
              Sign out
            </button>
          </div>
        </div>
        {nav.length > 0 && (
          <nav className="mx-auto flex max-w-6xl gap-1 px-4">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  cn(
                    "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "border-brand-600 font-medium text-brand-700"
                      : "border-transparent text-slate-500 hover:text-slate-900",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
