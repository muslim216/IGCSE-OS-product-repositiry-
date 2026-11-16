import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import {
  BEHIND,
  WEEKS,
  overviewWith,
  plan,
  renderView,
  slot,
  stubPlanApi,
  pinTodayToWednesday,
} from "./planFixtures";

/* T-078: the plan opens on this week and the next three, one line per lesson,
   one notice region. "Today" is fixed so the folds are deterministic. */

function stub(overview: Record<string, unknown>, failDraft = false) {
  stubPlanApi(
    () => overviewWith(overview),
    ({ url, method, json }) =>
      method === "POST" && url.pathname.endsWith("/draft") && failDraft
        ? json({ detail: "The draft service is down." }, 500)
        : undefined,
  );
}

pinTodayToWednesday();

test("this week and the next three are open; earlier and later weeks are folded and not rendered", async () => {
  stub({ accepted: plan(WEEKS) });
  renderView();
  expect(await screen.findByText("Week of 11 Jan 2027")).toBeInTheDocument();
  expect(screen.getByText("Week of 1 Feb 2027")).toBeInTheDocument();
  expect(screen.getByText("Earlier: 2 weeks")).toBeInTheDocument();
  expect(screen.getByText("Later: 2 weeks")).toBeInTheDocument();
  // Folded rows are not in the page at all until opened.
  expect(screen.queryByText("Week of 8 Feb 2027")).toBeNull();
  expect(screen.queryByText("Week of 4 Jan 2027")).toBeNull();
  fireEvent.click(screen.getByText("Later: 2 weeks"));
  expect(await screen.findByText("Week of 8 Feb 2027")).toBeInTheDocument();
  expect(screen.getByText("Week of 15 Feb 2027")).toBeInTheDocument();
});

test("a plan wholly in the future still opens on its first weeks", async () => {
  stub({ accepted: plan([slot(1, "2027-03-01"), slot(2, "2027-03-08")]) });
  renderView();
  expect(await screen.findByText("Week of 1 Mar 2027")).toBeInTheDocument();
  expect(screen.queryByText(/Earlier:/)).toBeNull();
});

test("a taught lesson shows one tick with text for screen readers, an untaught one shows nothing", async () => {
  stub({
    accepted: plan([
      slot(1, "2027-01-11", { provenance: "confirmed", lesson_id: 4, lesson_origin: "plan" }),
      slot(2, "2027-01-14"),
    ]),
  });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  const rows = screen.getAllByRole("listitem");
  const taught = within(rows[0]);
  expect(taught.getByText("taught")).toHaveClass("sr-only");
  expect(rows[0].querySelector("svg")).not.toBeNull();
  expect(within(rows[1]).queryByText("taught")).toBeNull();
  // No coloured status pill remains.
  expect(rows[0].querySelector(".rounded-full")).toBeNull();
});

test("Edit and Cancel are focusable controls revealed by focus, and a labelled ... button opens them on touch", async () => {
  stub({ accepted: plan([slot(1, "2027-01-14")]) });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  const edit = screen.getByRole("button", { name: "Edit, 14 Jan 2027, C1 Atoms" });
  const group = edit.parentElement as HTMLElement;
  // Hover or focus reveals them on a wide screen; they are never mouse-only.
  expect(group.className).toContain("group-focus-within:opacity-100");
  expect(group.className).toContain("group-hover:opacity-100");
  edit.focus();
  expect(edit).toHaveFocus();
  // On a phone they sit behind a labelled button.
  const more = screen.getByRole("button", { name: "More actions, 14 Jan 2027, C1 Atoms" });
  expect(more).toHaveAttribute("aria-expanded", "false");
  expect(group.className).toContain("hidden");
  fireEvent.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  expect(group.className).not.toMatch(/(^|\s)hidden(\s|$)/);
});

test("an error wins over the behind banner: only one notice shows", async () => {
  stub(
    {
      accepted: plan([slot(1, "2027-01-11")], {}),
      draft: plan([], { accepted_at: null }),
      progress: BEHIND,
    },
    true,
  );
  renderView();
  expect(await screen.findByText(/haven't been recorded since/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Draft a new plan" }));
  expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
  expect(screen.queryByText(/haven't been recorded since/)).toBeNull();
});

test("the behind banner shows when nothing outranks it", async () => {
  stub({ accepted: plan([slot(1, "2027-01-11")]), progress: BEHIND });
  renderView();
  await waitFor(() => expect(screen.getByText(/haven't been recorded since/)).toBeInTheDocument());
});
