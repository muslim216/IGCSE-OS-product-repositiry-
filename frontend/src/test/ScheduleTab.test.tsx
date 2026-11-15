import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import ScheduleTab from "../tutor/tabs/ScheduleTab";

/* T-078: the plan first, "Record a lesson" one button, settings behind one button. */

vi.mock("../tutor/GroupLayout", () => ({
  useGroupContext: () => ({ group: { subject: { id: 3 } }, groupId: 5 }),
}));

const PLAN_BODY = { id: 1, exam_date: "2027-05-10", breaks: [], slots: [] };
const SLOT_ROW = { id: 1, weekday: 1, start_time: "16:00:00", duration_min: 60 };

/** `existing` = the class already has a plan and a timetable. */
function stub(existing = false) {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if ((init?.method ?? "GET") === "POST" && url.pathname === "/api/v1/lessons") {
        posts.push(JSON.parse(String(init?.body)));
        return json({ id: 1 }, 201);
      }
      if (url.pathname.endsWith("/topics"))
        return json([{ id: 11, code: "1.1", title: "Atoms", parent_id: null, weight: 1 }]);
      if (url.pathname.endsWith("/lessons") && (init?.method ?? "GET") === "GET")
        return json(existing ? [SLOT_ROW] : []);
      if (url.pathname.endsWith("/plan"))
        return json({
          draft: null,
          accepted: existing ? PLAN_BODY : null,
          timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        });
      if (url.pathname.endsWith("/next-lesson")) return json(null);
      if (url.pathname.endsWith("/me/organization"))
        return json({ id: 1, name: "Org", timezone: "UTC" });
      return json([]);
    }),
  );
  return posts;
}

function renderTab(entry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <ScheduleTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("the plan comes first and the record form is closed until asked for", async () => {
  stub();
  renderTab();
  const planHeading = await screen.findByText("Lesson plan");
  const record = screen.getByRole("button", { name: "Record a lesson" });
  expect(screen.queryByRole("button", { name: "Record lesson" })).toBeNull();
  // The button sits above the plan.
  expect(
    record.compareDocumentPosition(planHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

test("Record a lesson opens the form in place and Cancel closes it", async () => {
  stub();
  renderTab();
  fireEvent.click(await screen.findByRole("button", { name: "Record a lesson" }));
  expect(await screen.findByRole("button", { name: "Record lesson" })).toBeInTheDocument();
  // The pressed button stays, as a disclosure toggle.
  const toggle = screen.getByRole("button", { name: "Record a lesson" });
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Record lesson" })).toBeNull());
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
});

test("a link from a lesson reminder opens the form straight away", async () => {
  stub();
  window.history.pushState({}, "", "/?slot=9");
  renderTab("/?slot=9");
  expect(await screen.findByRole("button", { name: "Record lesson" })).toBeInTheDocument();
  window.history.pushState({}, "", "/");
});

test("Plan settings holds the timetable and the plan inputs", async () => {
  stub(true);
  renderTab();
  const button = await screen.findByRole("button", { name: "Plan settings" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  const region = screen.getByRole("region", { name: "Plan settings" });
  expect(region).toBeVisible();
  expect(region.textContent).toMatch(/timetable|weekly/i);
  expect(region.textContent).toMatch(/exam date/i);
});

test("closing Plan settings keeps what was typed", async () => {
  stub(true);
  renderTab();
  const button = await screen.findByRole("button", { name: "Plan settings" });
  fireEvent.click(button);
  const exam = screen.getByLabelText(/exam date/i) as HTMLInputElement;
  fireEvent.change(exam, { target: { value: "2027-06-01" } });
  fireEvent.click(button);
  fireEvent.click(button);
  expect((screen.getByLabelText(/exam date/i) as HTMLInputElement).value).toBe("2027-06-01");
});

test("opening the form moves focus to its heading, and the pressed button stays", async () => {
  stub(true);
  renderTab();
  const toggle = await screen.findByRole("button", { name: "Record a lesson" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  const heading = await screen.findByRole("heading", { name: "Record a lesson you taught" });
  expect(heading).toHaveFocus();
  expect(toggle.getAttribute("aria-controls")).toBeTruthy();
  expect(document.getElementById(toggle.getAttribute("aria-controls") as string)).toContainElement(
    heading,
  );
});

test("saving a lesson closes the form, says so, and returns focus to the button", async () => {
  const posts = stub(true);
  renderTab();
  const toggle = await screen.findByRole("button", { name: "Record a lesson" });
  fireEvent.click(toggle);
  const submit = await screen.findByRole("button", { name: "Record lesson" });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  await waitFor(() => expect(posts).toHaveLength(1));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Record lesson" })).toBeNull());
  // The live region was mounted before the save, so the change is announced.
  expect(screen.getByText("Lesson recorded.")).toHaveAttribute("role", "status");
  expect(toggle).toHaveFocus();
});

test("Plan settings is open by default for a class with no plan and no timetable", async () => {
  stub(false);
  renderTab();
  const button = await screen.findByRole("button", { name: "Plan settings" });
  await waitFor(() => expect(button).toHaveAttribute("aria-expanded", "true"));
  expect(screen.getByRole("region", { name: "Plan settings" })).toBeVisible();
});

test("Plan settings stays closed when the class has a plan and a timetable", async () => {
  stub(true);
  renderTab();
  const button = await screen.findByRole("button", { name: "Plan settings" });
  await screen.findByText("Lesson plan");
  await waitFor(() => expect(screen.queryByText(/Loading/)).toBeNull());
  expect(button).toHaveAttribute("aria-expanded", "false");
});

test("?settings=1 opens Plan settings, also on in-app navigation", async () => {
  stub(true);
  renderTab("/?settings=1");
  const button = await screen.findByRole("button", { name: "Plan settings" });
  expect(button).toHaveAttribute("aria-expanded", "true");
});

test("?date= alone opens the record form", async () => {
  stub(true);
  renderTab("/?date=2027-01-05");
  expect(await screen.findByRole("button", { name: "Record lesson" })).toBeInTheDocument();
});

test("saving a lesson clears ?slot= and ?date= through the router", async () => {
  stub(true);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Where() {
    return <p data-testid="where">{useLocation().search}</p>;
  }
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/?date=2027-01-05&settings=0"]}>
        <ScheduleTab />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const submit = await screen.findByRole("button", { name: "Record lesson" });
  await waitFor(() => expect(submit).toBeEnabled());
  expect(screen.getByTestId("where").textContent).toContain("date=2027-01-05");
  fireEvent.click(submit);
  await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("?settings=0"));
});
