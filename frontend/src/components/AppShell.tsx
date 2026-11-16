import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
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
      one level below it (an assignment under Homework) keeps it lit. */
  also?: string[];
}

/** Active on its own path or under any `also` prefix. Computed here rather than
    by NavLink because NavLink only knows the exact match, and both the styling
    and aria-current must agree about a nested page (an assignment is "in"
    Classes). Exact, not prefix, for the item itself: the tutor home must
    not light for every tutor page. The value is what aria-current says: "page"
    on the destination's own page, "true" when the reader is somewhere inside
    it, so a screen reader does not announce two "current page" links. */
function currentOf(item: NavItem, pathname: string): "page" | "true" | undefined {
  const here = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (here === item.to) return "page";
  return (item.also ?? []).some((prefix) => here === prefix || here.startsWith(`${prefix}/`))
    ? "true"
    : undefined;
}

/** The most controls the bottom bar holds by default, More included: a list of
    this many fits with no More, a longer one keeps one fewer tab and folds the
    rest in. The tutor's bar is given a higher ceiling (`barSize`) because its
    six destinations read best as four tabs and More; the student bar stays as
    it was. */
const DEFAULT_BAR_SIZE = 4;

function Brand() {
  return <AvoraLockup className="px-1" />;
}

function SidebarLink({ item }: { item: NavItem }) {
  const { pathname } = useLocation();
  const current = currentOf(item, pathname);
  return (
    <Link
      to={item.to}
      aria-current={current}
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
function BottomTab({ item }: { item: NavItem }) {
  const { pathname } = useLocation();
  const current = currentOf(item, pathname);
  return (
    <Link
      to={item.to}
      aria-current={current}
      className={`flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium avora-press transition ${
        current ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
      }`}
    >
      <item.icon aria-hidden className="h-5 w-5 shrink-0" />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

/** The tutor's name menu: a real menu button. It opens on click, Enter or
    Space, puts focus on the first entry, moves with the arrow keys, Home and
    End, and closes on Escape (focus back on the button) or Tab. Sign out is the
    one action in it; the rest are links. `placement` says which way it opens,
    because the sidebar's button sits at the bottom of the screen and the phone
    header's at the top. */
function AccountMenu({
  items,
  placement,
  compact,
  title,
}: {
  items: NavItem[];
  placement: "above" | "below";
  compact?: boolean;
  /** The reader's role, printed under their name. */
  title: string;
}) {
  const { user, signOut } = useAuth();
  const { pathname } = useLocation();
  // The page it was opened on, rather than a plain flag: a bottom-tab tap or
  // the browser's Back changes the page without touching the menu, and a menu
  // still open over the new page is wrong. Open only while still on that page.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const setOpen = (value: boolean | ((v: boolean) => boolean)) =>
    setOpenAt((at) =>
      (typeof value === "function" ? value(at === pathname) : value) ? pathname : null,
    );
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpenAt(null);
      button.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  function onMenuKey(e: ReactKeyboardEvent<HTMLElement>) {
    const entries = [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    const at = entries.indexOf(document.activeElement as HTMLElement);
    const move = (i: number) => {
      e.preventDefault();
      entries[(i + entries.length) % entries.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(entries.length - 1);
    else if (e.key === "Tab") {
      // Focus goes to the button before the menu unmounts, so Tab moves on from
      // there instead of from an element that no longer exists.
      button.current?.focus();
      setOpen(false);
    }
  }

  const itemClass =
    "flex min-h-[44px] w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition hover:bg-surface-muted";
  return (
    <div className={`relative ${compact ? "" : "min-w-0 flex-1"}`}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={compact ? `Your account: ${user?.name ?? ""}` : undefined}
        onClick={() => setOpen((v) => !v)}
        className={
          compact
            ? "grid min-h-[44px] min-w-[44px] place-items-center rounded-full"
            : "-ml-1 flex w-full min-w-0 items-center gap-2.5 rounded-md p-1 text-left transition hover:bg-surface"
        }
      >
        <InitialsAvatar name={user?.name ?? "?"} size={compact ? "sm" : undefined} />
        {!compact && (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-ink-900">{user?.name}</span>
            <span className="block truncate text-xs text-ink-500">{title}</span>
          </span>
        )}
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            onClick={() => {
              setOpen(false);
              button.current?.focus();
            }}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div
            ref={menu}
            role="menu"
            aria-label="Account"
            onKeyDown={onMenuKey}
            className={`absolute z-40 min-w-48 rounded-lg border border-line bg-surface py-1 shadow-lg ${
              placement === "above" ? "bottom-full left-0 mb-2" : "right-0 top-full mt-2"
            }`}
          >
            {items.map((item) => {
              const current = currentOf(item, pathname);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  role="menuitem"
                  aria-current={current}
                  onClick={() => setOpen(false)}
                  className={`${itemClass} ${current ? "font-medium text-brand-600" : "text-ink-700"}`}
                >
                  <item.icon aria-hidden className="h-[18px] w-[18px] shrink-0" />
                  {item.label}
                </Link>
              );
            })}
            <button
              type="button"
              role="menuitem"
              onClick={signOut}
              className={`${itemClass} text-ink-700`}
            >
              <LogOut aria-hidden className="h-[18px] w-[18px] shrink-0" />
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** The overflow control and the sheet it opens. Every destination that does not
    fit the bar is reachable here, so nothing the sidebar offers is lost on a
    phone (the slot split is preserved: "bottom"-slot items live here, never as a
    primary tab). The button is lit while the current page is one of them, so a
    reader on Settings can tell where they are. */
function MoreTab({ items }: { items: NavItem[] }) {
  const { pathname } = useLocation();
  // Open only on the page it was opened on (see AccountMenu), so a tab tap or
  // Back closes it.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === pathname;
  const setOpen = (value: boolean | ((v: boolean) => boolean)) =>
    setOpenAt((at) =>
      (typeof value === "function" ? value(at === pathname) : value) ? pathname : null,
    );
  const sheet = useId();
  const current = items.find((item) => currentOf(item, pathname));
  const inside = current !== undefined;
  const button = useRef<HTMLButtonElement>(null);

  // Escape closes the sheet and hands focus back to the control that opened it,
  // so a keyboard reader is not left on an element that just disappeared.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpenAt(null);
      button.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative flex flex-1">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={open ? sheet : undefined}
        onClick={() => setOpen((v) => !v)}
        className={`flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium transition ${
          open || inside ? "text-brand-600" : "text-ink-500 hover:text-ink-900"
        }`}
      >
        <MoreHorizontal aria-hidden className="h-5 w-5 shrink-0" />
        {/* The button is lit while the page is inside it, which a screen reader
            cannot see; the sr-only suffix names the page. It sits inside the
            label's own span so the name reads "More, current page: Classes". */}
        <span>
          More
          {current && <span className="sr-only">, current page: {current.label}</span>}
        </span>
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
          {/* A plain disclosure of links: Tab walks them, so it claims no menu
              behaviour it does not have. */}
          <div
            id={sheet}
            role="group"
            aria-label="More"
            className="absolute bottom-full right-2 z-40 mb-2 max-h-[calc(100dvh-8rem)] min-w-44 overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg"
          >
            {items.map((item) => {
              const current = currentOf(item, pathname);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  aria-current={current}
                  onClick={() => setOpen(false)}
                  className={`flex min-h-[44px] items-center gap-2.5 px-3 py-2.5 text-sm -outline-offset-2 transition ${
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
  accountMenu,
  barSize = DEFAULT_BAR_SIZE,
}: {
  title: string;
  nav?: NavItem[];
  /** Where the avatar leads: the reader's own settings. */
  accountPath: string;
  /** When given, the name becomes a menu button listing these and Sign out,
      instead of a plain link to `accountPath`. */
  accountMenu?: NavItem[];
  /** How many controls the phone bar holds, More included, before it folds
      the rest into More. */
  barSize?: number;
}) {
  const { user, signOut } = useAuth();
  const { pathname, key: navigation } = useLocation();
  const mainNav = nav.filter((item) => item.slot !== "bottom");
  const bottomNav = nav.filter((item) => item.slot === "bottom");

  // The bottom bar shows main-workflow destinations first. When everything fits,
  // "bottom"-slot items trail after; when it does not, the bar keeps barSize - 1
  // primary tabs and folds the remainder — including every "bottom"-slot item —
  // into More, so a phone never loses a destination and the slot split holds.
  const fits = mainNav.length + bottomNav.length <= barSize;
  const tabItems = fits ? [...mainNav, ...bottomNav] : mainNav.slice(0, barSize - 1);
  const overflowItems = fits ? [] : [...mainNav.slice(barSize - 1), ...bottomNav];

  return (
    <div className="min-h-screen md:flex">
      <a
        href="#main"
        onClick={(e) => {
          // A hash link would hand the URL to the router; focus the landmark directly.
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
        className="sr-only z-50 rounded-md bg-surface px-4 py-2 text-sm font-medium text-ink-900 shadow-lg focus:not-sr-only focus:fixed! focus:left-4 focus:top-4 focus:px-4 focus:py-2"
      >
        Skip to main content
      </a>
      <AvoraGrain />
      {/* Desktop: fixed left sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between overflow-y-auto border-r border-line bg-canvas px-4 py-6 md:flex print:hidden">
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

          {/* An "AI Guidance" link pointed at /tutor — the Overview page, then called Today, whose
              sidebar it sat in. A navigation item that goes nowhere teaches the
              reader that the nav lies, and it was advertising a destination the
              product does not have. Removed rather than repointed: the guidance
              belongs on that page itself, which is where PRs 13-15 put it. */}

          <div className="mt-2 flex items-center gap-1 px-1">
            {accountMenu ? (
              <AccountMenu items={accountMenu} placement="above" title={title} />
            ) : (
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
            )}
            <ActivityMenu />
            {!accountMenu && (
              <button
                onClick={signOut}
                aria-label="Sign out"
                className="rounded-md p-1.5 text-ink-500 transition hover:bg-surface hover:text-ink-900"
              >
                <LogOut aria-hidden className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </aside>

      {/* Mobile: a compact top bar for identity + account, and a fixed bottom
          tab bar for navigation (the reachable-with-a-thumb position). */}
      <header className="sticky top-0 z-10 border-b border-line bg-canvas md:hidden print:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <Brand />
          <div className="flex items-center gap-2 text-sm">
            {accountMenu ? (
              <AccountMenu items={accountMenu} placement="below" compact title={title} />
            ) : (
              <NavLink to={accountPath} aria-label="Your account" className="rounded-full">
                <InitialsAvatar name={user?.name ?? "?"} size="sm" />
              </NavLink>
            )}
            <ActivityMenu />
            {!accountMenu && (
              <button
                onClick={signOut}
                aria-label="Sign out"
                className="rounded-md p-1.5 text-ink-500 transition hover:text-ink-900"
              >
                <LogOut aria-hidden className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </header>

      <main
        id="main"
        tabIndex={-1}
        className="min-w-0 outline-none flex-1 px-4 py-6 pb-tabbar md:px-10 md:py-8 print:p-0"
      >
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
          className="pb-safe pl-safe pr-safe fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-canvas md:hidden print:hidden"
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
