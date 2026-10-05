const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayAndMonth(iso: string): { day: number; month: number } {
  // The date part of the stored instant, read as written. The send closes on
  // the tutor's clock, and re-reading it in the browser's zone could move the
  // label to the day before or after for a reader abroad.
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { day: d, month: m - 1 };
}

/** "4–11 Oct" or "28 Sep – 5 Oct" for a send's week. */
export function weekLabel(startIso: string, endIso: string): string {
  const a = dayAndMonth(startIso);
  const b = dayAndMonth(endIso);
  return a.month === b.month
    ? `${a.day}–${b.day} ${MONTHS[b.month]}`
    : `${a.day} ${MONTHS[a.month]} – ${b.day} ${MONTHS[b.month]}`;
}

/** The three shells a send can be read in. */
export type ShellHome = "/tutor" | "/student" | "/parent";

/** The shell for a role, for the one place that knows only the role. */
export function shellFor(role: string): ShellHome {
  return role === "student" ? "/student" : role === "parent" ? "/parent" : "/tutor";
}

/** Where a send opens: inside the reader's own shell. */
export function weeklySendPath(home: ShellHome, id: number): string {
  return `${home}/weekly/${id}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
