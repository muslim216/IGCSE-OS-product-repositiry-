import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export interface NavItem {
  to: string;
  label: string;
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 glass border-x-0 border-t-0">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <span
              className="grid h-8 w-8 place-items-center rounded-lg text-xs font-bold text-slate-950"
              style={{
                background: "linear-gradient(135deg, #22d3ee, #a78bfa)",
                boxShadow: "0 0 20px -4px rgba(34, 211, 238, 0.7)",
              }}
            >
              OS
            </span>
            <span className="text-lg font-semibold text-slate-100">IGCSE Student OS</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs uppercase tracking-wide text-slate-400">
              {title}
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-400">{user?.name}</span>
            <button
              onClick={signOut}
              className="rounded-md px-2 py-1 text-slate-400 transition hover:text-slate-100"
            >
              Sign out
            </button>
          </div>
        </div>
        {nav.length > 0 && (
          <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-3">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition ${
                    isActive
                      ? "text-slate-950"
                      : "text-slate-400 hover:bg-slate-100 hover:text-slate-100"
                  }`
                }
                style={({ isActive }) =>
                  isActive
                    ? {
                        background: "linear-gradient(135deg, #22d3ee, #a78bfa)",
                        boxShadow: "0 0 16px -4px rgba(34, 211, 238, 0.6)",
                      }
                    : undefined
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
