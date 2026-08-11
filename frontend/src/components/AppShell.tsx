import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { LogOut, MoreHorizontal, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { InitialsAvatar } from "./ui";
import { AvoraGrain, AvoraLockup } from "./brand";
import ActivityMenu from "./ActivityMenu";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** "bottom" items sit apart from the main workflow nav. */
  slot?: "main" | "bottom";
}

/** The most tabs the bottom bar shows before the rest fold into "More". Four
    plus a More control is the comfortable ceiling for a phone-width bar with
    ≥44px targets. */
const MAX_TABS = 4;

function Brand() {
  return <AvoraLockup className="px-1" />;
}

function SidebarLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition ${
          isActive
            ? "bg-brand-600 font-medium text-canvas"
            : "text-ink-500 hover:bg-surface hover:text-ink-900"
        }`
      }
    >
      <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
      {item.label}
    </NavLink>
  );
}

/** A single destination in the fixed bottom bar: icon over label, ≥44px tall,
    the touch-target floor WCAG 2.5.5 sets. */
function BottomTab({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  return (
    <NavLink
      to={item.to}
      end
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium transition ${
          isActive ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
        }`
      }
    >
      <item.icon aria-hidden className="h-5 w-5 shrink-0" />
      <span className="truncate">{item.label}</span>
    </NavLink>
  );
}

/** The overflow control and the sheet it opens. Every destination that does not
    fit the bar is reachable here, so nothing the sidebar offers is lost on a
    phone (the slot split is preserved: "bottom"-slot items live here, never as a
    primary tab). */
function MoreTab({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative flex flex-1">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={`flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium transition ${
          open ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
        }`}
      >
        <MoreHorizontal aria-hidden className="h-5 w-5 shrink-0" />
        <span>More</span>
      </button>
      {open && (
        <>
          {/* Click-away layer so a tap outside closes the sheet. */}
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div
            role="menu"
            className="absolute bottom-full right-2 z-40 mb-2 min-w-44 rounded-lg border border-line bg-surface py-1 shadow-lg"
          >
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                role="menuitem"
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2.5 text-sm transition ${
                    isActive ? "font-medium text-brand-600" : "text-ink-700 hover:bg-surface-muted"
                  }`
                }
              >
                <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
                {item.label}
              </NavLink>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function AppShell({ title, nav = [] }: { title: string; nav?: NavItem[] }) {
  const { user, signOut } = useAuth();
  const mainNav = nav.filter((item) => item.slot !== "bottom");
  const bottomNav = nav.filter((item) => item.slot === "bottom");

  // The bottom bar shows main-workflow destinations first. When everything fits,
  // "bottom"-slot items trail after; when it does not, the bar keeps MAX_TABS-1
  // primary tabs and folds the remainder — including every "bottom"-slot item —
  // into More, so a phone never loses a destination and the slot split holds.
  const fits = mainNav.length + bottomNav.length <= MAX_TABS;
  const tabItems = fits ? [...mainNav, ...bottomNav] : mainNav.slice(0, MAX_TABS - 1);
  const overflowItems = fits ? [] : [...mainNav.slice(MAX_TABS - 1), ...bottomNav];

  return (
    <div className="min-h-screen md:flex">
      <AvoraGrain />
      {/* Desktop: fixed left sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between overflow-y-auto border-r border-line bg-canvas px-4 py-6 md:flex">
        <div className="flex flex-col gap-8">
          <Brand />
          <div className="flex flex-col gap-1">
            <span className="px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
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

          {/* An "AI Guidance" link pointed at /tutor — the Today page whose
              sidebar it sat in. A navigation item that goes nowhere teaches the
              reader that the nav lies, and it was advertising a destination the
              product does not have. Removed rather than repointed: the guidance
              belongs on Today itself, which is where PRs 13-15 put it. */}

          <div className="mt-2 flex items-center gap-2.5 px-1">
            <InitialsAvatar name={user?.name ?? "?"} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-900">{user?.name}</p>
              <p className="truncate text-xs text-ink-500">{title}</p>
            </div>
            <ActivityMenu />
            <button
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-ink-500 transition hover:bg-surface hover:text-ink-900"
            >
              <LogOut aria-hidden className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile: a compact top bar for identity + account, and a fixed bottom
          tab bar for navigation (the reachable-with-a-thumb position). */}
      <header className="sticky top-0 z-10 border-b border-line bg-canvas md:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <div className="flex items-center gap-2 text-sm">
            <span className="truncate text-ink-500">{user?.name}</span>
            <ActivityMenu />
            <button
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-ink-500 transition hover:text-ink-900"
            >
              <LogOut aria-hidden className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="min-w-0 flex-1 px-4 py-6 pb-tabbar md:px-10 md:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>

      {nav.length > 0 && (
        <nav
          aria-label={`${title} tabs`}
          className="pb-safe pl-safe pr-safe fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-canvas md:hidden"
        >
          {tabItems.map((item) => (
            <BottomTab key={item.to} item={item} />
          ))}
          {overflowItems.length > 0 && <MoreTab items={overflowItems} />}
        </nav>
      )}
    </div>
  );
}
