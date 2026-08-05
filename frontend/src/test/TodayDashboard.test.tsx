import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

const TUTOR = {
  id: 1,
  email: "demo-tutor@example.com",
  username: null,
  role: "tutor",
  name: "Amina Rahman",
};

const SUBJECT = { id: 1, exam_board: "CIE", code: "0625", name: "Physics", grade_scale: "9-1" };

function stubFetch(empty = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

      if (url.includes("/auth/me")) return json(TUTOR);
      if (empty) return json([]);

      if (url.includes("/me/today-lessons")) {
        return json([
          {
            id: 1,
            group_id: 5,
            group_name: "Physics A",
            subject_name: "Physics",
            weekday: 2,
            start_time: "16:00:00",
            duration_min: 60,
            title: null,
          },
        ]);
      }
      if (url.includes("/analytics/groups/5")) {
        return json({
          weak_students: [
            { student_id: 9, student_name: "Aya Hassan", subject_name: "Physics", score: 42.5 },
            { student_id: 10, student_name: "Omar Ali", subject_name: "Physics", score: 81 },
          ],
          weak_topics: [],
          agreement: { total_marked_questions: 0, ai_agreed: 0, agreement_rate: null },
        });
      }
      if (url.includes("/assignments/attention")) {
        return json([
          {
            assignment_id: 3,
            assignment_title: "Forces worksheet",
            reason: "ai_marked",
            detail: null,
            submission_id: 7,
            student_name: "Aya Hassan",
          },
        ]);
      }
      if (url.includes("/groups")) {
        return json([{ id: 5, name: "Physics A", subject: SUBJECT, member_count: 2 }]);
      }
      return json([]);
    }),
  );
}

function renderDashboard() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.setItem(
    "igcse-os-tokens",
    JSON.stringify({ access_token: "t", refresh_token: "r", token_type: "bearer" }),
  );
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("shows today's sessions and learner readiness from real evidence", async () => {
  stubFetch();
  renderDashboard();

  expect(await screen.findByText(/Amina\./)).toBeInTheDocument();
  expect(await screen.findByText("16:00")).toBeInTheDocument();
  expect((await screen.findAllByText("Physics A")).length).toBeGreaterThan(0);

  expect(await screen.findByText("Aya Hassan")).toBeInTheDocument();
  expect(await screen.findByText("At risk")).toBeInTheDocument();
  expect(await screen.findByText("1 learner")).toBeInTheDocument();

  // "On track" labels both the filter tab and Omar's status badge.
  const omarRow = (await screen.findByText("Omar Ali")).closest("tr")!;
  expect(within(omarRow).getByText("On track")).toBeInTheDocument();

  const row = (await screen.findByText("Aya Hassan")).closest("tr")!;
  expect(within(row).getByRole("link", { name: /Review evidence/ })).toHaveAttribute(
    "href",
    "/tutor/students/9",
  );
});

test("the on-track filter narrows the table to learners who are on track", async () => {
  stubFetch();
  renderDashboard();
  await screen.findByText("Aya Hassan");

  fireEvent.click(screen.getByRole("button", { name: /On track/ }));

  await waitFor(() => expect(screen.queryByText("Aya Hassan")).not.toBeInTheDocument());
  expect(screen.getByText("Omar Ali")).toBeInTheDocument();
});

test("create lesson opens a dialog", async () => {
  stubFetch();
  renderDashboard();

  fireEvent.click(await screen.findByRole("button", { name: "Create lesson" }));
  expect(await screen.findByRole("dialog")).toHaveAccessibleName("Schedule a weekly lesson");
});

test("with no data it explains the empty state and invents no scores", async () => {
  stubFetch(true);
  renderDashboard();

  expect(await screen.findByText("No sessions today.")).toBeInTheDocument();
  expect(await screen.findByText("No readiness evidence yet.")).toBeInTheDocument();
  expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
});
