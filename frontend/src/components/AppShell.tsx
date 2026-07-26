import { Link, NavLink, Outlet } from "react-router-dom";
import { LogOut, Sparkles, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { InitialsAvatar } from "./ui";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** "bottom" items sit apart from the main workflow nav. */
  slot?: "main" | "bottom";
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-700 text-sm font-bold text-white">
        M
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-[0.06em] text-ink-900">
          MANARA
        </span>
        <span className="block text-[9px] font-semibold uppercase tracking-[0.2em] text-gold-600">
          by OASIS AI
        </span>
      </span>
    </div>
  );
}

function SidebarLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition ${
          isActive
            ? "bg-brand-50 font-medium text-brand-700"
            : "text-ink-500 hover:bg-surface-muted hover:text-ink-900"
        }`
      }
    >
      <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
      {item.label}
    </NavLink>
  );
}

function TabLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end
      className={({ isActive }) =>
        `flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition ${
          isActive ? "bg-brand-600 text-white" : "text-ink-500 hover:bg-surface-muted"
        }`
      }
    >
      <item.icon aria-hidden className="h-4 w-4 shrink-0" />
      {item.label}
    </NavLink>
  );
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();
  const mainNav = nav.filter((item) => item.slot !== "bottom");
  const bottomNav = nav.filter((item) => item.slot === "bottom");
  const isTutor = title === "Tutor";

  return (
    <div className="min-h-screen md:flex">
      {/* Desktop: fixed left sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between overflow-y-auto border-r border-line bg-surface px-4 py-6 md:flex">
        <div className="flex flex-col gap-8">
          <Brand />
          <div className="flex flex-col gap-1">
            <span className="px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-400">
              {title}
            </span>
            <nav aria-label={`${title} navigation`} className="flex flex-col gap-0.5">
              {mainNav.map((item) => (
                <SidebarLink key={item.to} item={item} />
              ))}
            </nav>
          </div>
        </div>

        <div className="flex flex-col gap-1 border-t border-line pt-4">
          {bottomNav.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}

          {isTutor && (
            <Link
              to="/tutor"
              className="flex items-start gap-2.5 rounded-md px-3 py-2 text-ink-700 transition hover:bg-surface-muted"
            >
              <Sparkles aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold-600" />
              <span className="leading-tight">
                <span className="block text-sm">AI Guidance</span>
                <span className="block text-xs text-ink-400">Evidence-grounded</span>
              </span>
            </Link>
          )}

          <div className="mt-2 flex items-center gap-2.5 px-1">
            <InitialsAvatar name={user?.name ?? "?"} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-900">{user?.name}</p>
              <p className="truncate text-xs text-ink-400">{title}</p>
            </div>
            <button
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-ink-400 transition hover:bg-surface-muted hover:text-ink-900"
            >
              <LogOut aria-hidden className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile: compact top bar with horizontal tabs */}
      <header className="sticky top-0 z-10 border-b border-line bg-surface md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <div className="flex items-center gap-2 text-sm">
            <span className="truncate text-ink-500">{user?.name}</span>
            <button
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-ink-400 transition hover:text-ink-900"
            >
              <LogOut aria-hidden className="h-4 w-4" />
            </button>
          </div>
        </div>
        {nav.length > 0 && (
          <nav aria-label={`${title} navigation`} className="flex gap-1 overflow-x-auto px-4 pb-3">
            {nav.map((item) => (
              <TabLink key={item.to} item={item} />
            ))}
          </nav>
        )}
      </header>

      <main className="min-w-0 flex-1 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
