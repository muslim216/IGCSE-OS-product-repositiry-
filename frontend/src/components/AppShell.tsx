import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export interface NavItem {
  to: string;
  label: string;
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-lg font-semibold text-slate-800">IGCSE Student OS</span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs uppercase tracking-wide text-slate-500">
              {title}
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-600">{user?.name}</span>
            <button onClick={signOut} className="text-slate-500 hover:text-slate-800">
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
                end
                className={({ isActive }) =>
                  `border-b-2 px-3 py-2 text-sm ${
                    isActive
                      ? "border-blue-600 font-medium text-blue-700"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`
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
