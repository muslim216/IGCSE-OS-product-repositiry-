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
      <span className="grid h-8 w-8 shrink-0 place-items-center border-2 border-black bg-arcade-mint font-mono text-xs font-black text-[#050308] shadow-[3px_3px_0px_0px_rgba(0,0,0,1)]">
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
          ? "flex flex-col gap-1"
          : "flex gap-1.5 overflow-x-auto"
      }
    >
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          className={({ isActive }) =>
            orientation === "vertical"
              ? `border-2 px-3 py-2 font-mono text-xs font-black uppercase tracking-wider transition ${
                  isActive
                    ? "border-black bg-arcade-mint text-[#050308] shadow-[3px_3px_0px_0px_rgba(0,0,0,1)]"
                    : "border-transparent text-[#9a8fb5] hover:border-black hover:bg-white/[0.04] hover:text-arcade-mint"
                }`
              : `whitespace-nowrap border-2 px-3 py-1.5 font-mono text-xs font-black uppercase tracking-wider transition ${
                  isActive
                    ? "border-black bg-arcade-mint text-[#050308] shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]"
                    : "border-transparent text-[#9a8fb5] hover:border-black hover:text-arcade-mint"
                }`
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
          <div className="arcade-trim text-arcade-magenta" aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="px-3 font-mono text-[11px] font-black uppercase tracking-wider text-arcade-mint">
              {title}
            </span>
            <NavLinks nav={nav} orientation="vertical" />
          </div>
        </div>

        <div className="flex items-center gap-2.5 border-t-4 border-black px-1 pt-4">
          <span className="grid h-8 w-8 shrink-0 place-items-center border-2 border-black bg-arcade-panel-2 font-mono text-xs font-black text-arcade-mint">
            {initials(user?.name ?? "?")}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-200">{user?.name}</p>
            <button
              onClick={signOut}
              className="font-mono text-[10px] font-black uppercase tracking-wider text-slate-500 transition hover:text-arcade-mint"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile: top bar with horizontal tabs */}
      <header className="glass sticky top-0 z-10 md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-400">{user?.name}</span>
            <button
              onClick={signOut}
              className="px-2 py-1 font-mono text-[10px] font-black uppercase tracking-wider text-slate-400 transition hover:text-arcade-mint"
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
