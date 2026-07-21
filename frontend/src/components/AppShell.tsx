import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export interface NavItem {
  to: string;
  label: string;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <span
        className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-xs font-bold text-slate-950"
        style={{
          background: "linear-gradient(135deg, #22d3ee, #a78bfa)",
          boxShadow: "0 0 20px -4px rgba(34, 211, 238, 0.7)",
        }}
      >
        OS
      </span>
      <span className="text-[15px] font-semibold leading-tight tracking-tight text-slate-100">
        IGCSE Student OS
      </span>
    </div>
  );
}

function NavLinks({ nav, orientation }: { nav: NavItem[]; orientation: "vertical" | "horizontal" }) {
  return (
    <nav
      className={
        orientation === "vertical"
          ? "flex flex-col gap-0.5"
          : "flex gap-1 overflow-x-auto"
      }
    >
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          className={({ isActive }) =>
            orientation === "vertical"
              ? `group relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "text-slate-50"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
                }`
              : `whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition ${
                  isActive
                    ? "text-slate-950"
                    : "text-slate-400 hover:bg-slate-100 hover:text-slate-100"
                }`
          }
          style={({ isActive }) =>
            !isActive
              ? undefined
              : orientation === "vertical"
                ? {
                    background:
                      "linear-gradient(90deg, rgba(34,211,238,0.16), rgba(167,139,250,0.10))",
                    boxShadow: "inset 2px 0 0 0 var(--color-neon-cyan)",
                  }
                : {
                    background: "linear-gradient(135deg, #22d3ee, #a78bfa)",
                    boxShadow: "0 0 16px -4px rgba(34, 211, 238, 0.6)",
                  }
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();

  return (
    <div className="min-h-screen md:flex">
      {/* Desktop: fixed left sidebar */}
      <aside className="sidebar hidden shrink-0 flex-col justify-between md:flex">
        <div className="flex flex-col gap-8">
          <Brand />
          <div className="flex flex-col gap-1">
            <span className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              {title}
            </span>
            <NavLinks nav={nav} orientation="vertical" />
          </div>
        </div>

        <div className="flex items-center gap-2.5 border-t border-white/[0.06] px-1 pt-4">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-white/[0.06] text-xs font-semibold text-slate-300">
            {initials(user?.name ?? "?")}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-200">{user?.name}</p>
            <button
              onClick={signOut}
              className="text-xs text-slate-500 transition hover:text-slate-200"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile: top bar with horizontal tabs */}
      <header className="glass sticky top-0 z-10 border-x-0 border-t-0 md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <div className="flex items-center gap-3 text-sm">
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
          <div className="px-4 pb-3">
            <NavLinks nav={nav} orientation="horizontal" />
          </div>
        )}
      </header>

      <main className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-10">
        <div className="mx-auto max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
