import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import {
  type Slot,
  plan,
  renderView,
  slot,
  stubPlanApi,
  pinTodayToWednesday,
} from "./planFixtures";

/* T-078: errors are heard, and focus is never dropped to the page after an edit or a cancel. */

const OUTCOME = {
  status: "drafted",
  drafted_at: "2027-01-04T09:00:00Z",
  weight_source: "ai",
  degraded_reason: null,
  guidance_used: false,
  guidance_note: null,
  defaulted_chapters: 0,
  chapters: [],
  failure_code: null,
  failure_message: null,
};

/** A small server: PATCH moves the slot, cancel marks it cancelled. */
function stub(opts: { slots?: Slot[]; draft?: unknown; failAccept?: boolean; shifted?: boolean }) {
  const slots = opts.slots ?? [];
  const overview = () => ({
    draft: opts.draft ?? null,
    accepted: plan(slots),
    timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
    progress: null,
  });
  stubPlanApi(overview, ({ url, method, init, json }) => {
    if (method === "POST" && url.pathname.endsWith("/accept") && opts.failAccept)
      return json({ detail: "The accept service is down." }, 500);
    const target = /\/slots\/(\d+)/.exec(url.pathname);
    if (method === "PATCH" && target) {
      const s = slots.find((x) => x.id === Number(target[1]))!;
      Object.assign(s, JSON.parse(String(init?.body)));
      return json(s);
    }
    if (method === "POST" && target && url.pathname.endsWith("/cancel")) {
      slots.find((x) => x.id === Number(target[1]))!.cancelled = true;
      return json({
        shifted: opts.shifted ?? true,
        moved: 1,
        message: null,
        plan: overview(),
      });
    }
    return undefined;
  });
}

pinTodayToWednesday();

test("an error from accepting lands in an alert region that was mounted before it", async () => {
  stub({
    slots: [],
    draft: plan([slot(10, "2027-01-14")], { accepted_at: null, outcome: OUTCOME }),
    failAccept: true,
  });
  renderView();
  await screen.findByText("Week of 11 Jan 2027");
  const region = screen.getByRole("alert");
  expect(region.textContent).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "Accept plan" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Accept plan" }));
  await waitFor(() => expect(region.textContent).toMatch(/went wrong|accept service/i));
});

test("after saving a lesson to another week, focus is on that lesson's Edit button", async () => {
  stub({ slots: [slot(1, "2027-01-14"), slot(2, "2027-01-21")] });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: /^Edit, 14 Jan 2027/ }));
  fireEvent.change(screen.getByLabelText("Lesson date"), { target: { value: "2027-01-28" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));
  const moved = await screen.findByRole("button", { name: /^Edit, 28 Jan 2027/ });
  await waitFor(() => expect(moved).toHaveFocus());
});

test("a lesson moved into a closed fold hands focus to that fold's summary", async () => {
  stub({ slots: [slot(1, "2027-01-14"), slot(2, "2027-01-21")] });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: /^Edit, 14 Jan 2027/ }));
  fireEvent.change(screen.getByLabelText("Lesson date"), { target: { value: "2027-03-04" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));
  const summary = await screen.findByText("Later: 1 week");
  await waitFor(() => expect(summary).toHaveFocus());
});

test("cancelling a lesson says so and moves focus to the next lesson's actions", async () => {
  stub({ slots: [slot(1, "2027-01-14"), slot(2, "2027-01-21")] });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: /^Cancel lesson, 14 Jan 2027/ }));
  const note = await screen.findByText("Lesson cancelled; later lessons moved.");
  expect(note.closest('[role="status"]')).not.toBeNull();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /^Edit, 21 Jan 2027/ })).toHaveFocus(),
  );
});

test("cancelling the last lesson with no shift still says it was cancelled", async () => {
  stub({ slots: [slot(1, "2027-01-14")], shifted: false });
  renderView();
  fireEvent.click(await screen.findByRole("button", { name: /^Cancel lesson, 14 Jan 2027/ }));
  expect(await screen.findByText("Lesson cancelled.")).toBeInTheDocument();
});
