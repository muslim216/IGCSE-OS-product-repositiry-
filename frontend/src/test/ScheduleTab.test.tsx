import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ScheduleTab from "../tutor/tabs/ScheduleTab";

/* T-078: the plan first, "Record a lesson" one button, settings behind one button. */

vi.mock("../tutor/GroupLayout", () => ({
  useGroupContext: () => ({ group: { subject: { id: 3 } }, groupId: 5 }),
}));

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
      if (url.pathname.endsWith("/plan"))
        return json({
          draft: null,
          accepted: null,
          timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        });
      if (url.pathname.endsWith("/next-lesson")) return json(null);
      if (url.pathname.endsWith("/me/organization"))
        return json({ id: 1, name: "Org", timezone: "UTC" });
      return json([]);
    }),
  );
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ScheduleTab />
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
  expect(screen.queryByRole("button", { name: "Record a lesson" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Record lesson" })).toBeNull());
  expect(screen.getByRole("button", { name: "Record a lesson" })).toBeInTheDocument();
});

test("a link from a lesson reminder opens the form straight away", async () => {
  stub();
  window.history.pushState({}, "", "/?slot=9");
  renderTab();
  expect(await screen.findByRole("button", { name: "Record lesson" })).toBeInTheDocument();
  window.history.pushState({}, "", "/");
});

test("Plan settings holds the timetable and the plan inputs", async () => {
  stub();
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
  stub();
  renderTab();
  const button = await screen.findByRole("button", { name: "Plan settings" });
  fireEvent.click(button);
  const exam = screen.getByLabelText(/exam date/i) as HTMLInputElement;
  fireEvent.change(exam, { target: { value: "2027-06-01" } });
  fireEvent.click(button);
  fireEvent.click(button);
  expect((screen.getByLabelText(/exam date/i) as HTMLInputElement).value).toBe("2027-06-01");
});
