import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { LogOut, MoreHorizontal, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { InitialsAvatar } from "./ui";
import { AvoraGrain, AvoraLockup } from "./brand";
import ActivityMenu from "./ActivityMenu";
import { ErrorBoundary } from "./page";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** "bottom" items sit apart from the main workflow nav. */
  slot?: "main" | "bottom";
  /** Extra path prefixes that count as being "in" this destination, so a page
      one level below it (a past paper under Papers & mocks) keeps it lit. */
  also?: string[];
}

/** Active on its own path or under any `also` prefix. Computed here rather than
    by NavLink because NavLink only knows the exact match, and both the styling
    and aria-current must agree about a nested page (a past paper is "in"
    Papers & mocks). Exact, not prefix, for the item itself: the tutor home must
    not light for every tutor page. */
function isCurrent(item: NavItem, pathname: string): boolean {
  const here = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return (
    here === item.to ||
    (item.also ?? []).some((prefix) => here === prefix || here.startsWith(`${prefix}/`))
  );
}

/** The most tabs the bottom bar shows before the rest fold into "More". Four
    plus a More control is the comfortable ceiling for a phone-width bar with
    ≥44px targets. */
const MAX_TABS = 4;

function Brand() {
  return <AvoraLockup className="px-1" />;
}

function SidebarLink({ item }: { item: NavItem }) {
  const { pathname } = useLocation();
  const current = isCurrent(item, pathname);
  return (
    <Link
      to={item.to}
      aria-current={current ? "page" : undefined}
      className={`avora-press flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition ${
        current
          ? "bg-brand-600 font-medium text-canvas"
          : "text-ink-500 hover:bg-surface hover:text-ink-900"
      }`}
    >
      <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
      {item.label}
    </Link>
  );
}

/** A single destination in the fixed bottom bar: icon over label, ≥44px tall,
    the touch-target floor WCAG 2.5.5 sets. */
function BottomTab({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const current = isCurrent(item, pathname);
  return (
    <Link
      to={item.to}
      aria-current={current ? "page" : undefined}
      onClick={onNavigate}
      className={`flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium avora-press transition ${
        current ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
      }`}
    >
      <item.icon aria-hidden className="h-5 w-5 shrink-0" />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

/** The overflow control and the sheet it opens. Every destination that does not
    fit the bar is reachable here, so nothing the sidebar offers is lost on a
    phone (the slot split is preserved: "bottom"-slot items live here, never as a
    primary tab). The button is lit while the current page is one of them, so a
    reader on Settings can tell where they are. */
function MoreTab({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const inside = items.some((item) => isCurrent(item, pathname));
  return (
    <div className="relative flex flex-1">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={`flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium transition ${
          open || inside ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
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
            {items.map((item) => {
              const current = isCurrent(item, pathname);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  role="menuitem"
                  aria-current={current ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={`flex items-center gap-2.5 px-3 py-2.5 text-sm transition ${
                    current ? "font-medium text-brand-600" : "text-ink-700 hover:bg-surface-muted"
                  }`}
                >
                  <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

export default function AppShell({
  title,
  nav = [],
  accountPath,
}: {
  title: string;
  nav?: NavItem[];
  /** Where the avatar leads: the reader's own settings. */
  accountPath: string;
}) {
  const { user, signOut } = useAuth();
  const { pathname, key: navigation } = useLocation();
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
          {/* A role heading over an empty list read as a broken sidebar (the
              parent role has one screen and no nav), so it only renders with
              something under it. */}
          {mainNav.length > 0 && (
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
          )}
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

          <div className="mt-2 flex items-center gap-1 px-1">
            <NavLink
              to={accountPath}
              className="-ml-1 flex min-w-0 flex-1 items-center gap-2.5 rounded-md p-1 transition hover:bg-surface"
              aria-label={`Your account: ${user?.name ?? ""}`}
            >
              <InitialsAvatar name={user?.name ?? "?"} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-900">{user?.name}</p>
                <p className="truncate text-xs text-ink-500">{title}</p>
              </div>
            </NavLink>
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
            <NavLink to={accountPath} aria-label="Your account" className="rounded-full">
              <InitialsAvatar name={user?.name ?? "?"} size="sm" />
            </NavLink>
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
          {/* Keyed by route, so each page mounts fresh, and reset by every
              navigation, so leaving a crash clears it even when only the query
              string changes. Keying on the navigation instead would also
              remount a healthy page each time its own nav link is clicked (a
              same-URL click is a replace with a new key), dropping anything
              unsaved on it. */}
          <ErrorBoundary key={pathname} resetKey={navigation}>
            <Outlet />
          </ErrorBoundary>
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
