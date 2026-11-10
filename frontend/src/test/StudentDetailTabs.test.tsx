import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";

/* The student page is a short summary and four tabs (T-041). Every control the
   old single page offered must still exist, in the tab the design gives it. */

let calls: string[] = [];

function stub(readinessStatus = 200) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname);
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      if (url.pathname === "/api/v1/readiness/students/2") {
        if (readinessStatus !== 200) return json({ detail: "x" }, readinessStatus);
        return json({
          student_id: 2,
          student_name: "Sara",
          subjects: [
            {
              subject_id: 5,
              subject_name: "Chemistry",
              exam_board: "CIE",
              grade_scale: "9-1",
              score: 60,
              predicted_grade: "5",
              status: "on_track",
              verdict: {
                status: "needs_attention",
                headline: "h",
                reason_topics: [],
                next_step: "n",
              },
              averaging_score: null,
              averaging_grade: null,
              marked_piece_count: 3,
              direction: "up",
              month_delta: null,
              topics_with_evidence: 1,
              topic_count: 2,
              homework_assignment_count: null,
              topics: [],
              weak_topics: [],
            },
          ],
        });
      }
      if (url.pathname.endsWith("/erasure")) return json(null);
      if (url.pathname.includes("/mistakes")) return json({ analysed_questions: 0 });
      return json([]);
    }),
  );
}

function Where() {
  const l = useLocation();
  const nav = useNavigate();
  return (
    <>
      <output data-testid="loc">{l.search}</output>
      <button onClick={() => nav(-1)}>history back</button>
    </>
  );
}

function renderPage(entry = "/tutor/students/2") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Where />
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

const key = (k: string) => fireEvent.keyDown(document.activeElement!, { key: k });
const tab = (name: string) => screen.findByRole("tab", { name });
const selected = () => screen.getByRole("tab", { selected: true }).textContent;

test("four tabs, Progress is the default, and the summary is above them", async () => {
  stub();
  renderPage();
  expect((await screen.findAllByRole("tab")).map((t) => t.textContent)).toEqual([
    "Progress",
    "Work",
    "Notes",
    "About",
  ]);
  expect(selected()).toBe("Progress");
  expect(screen.getByText(/Needs attention: Chemistry/)).toBeInTheDocument();
  expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Progress");
});

test("?tab=about opens About and an unknown tab falls back to Progress", async () => {
  stub();
  const first = renderPage("/tutor/students/2?tab=about");
  await tab("About");
  expect(selected()).toBe("About");
  first.unmount();
  renderPage("/tutor/students/2?tab=junk&group=3");
  await tab("About");
  expect(selected()).toBe("Progress");
});

test("arrow keys, Home and End move between tabs and only the open tab is tabbable", async () => {
  stub();
  renderPage();
  const progress = await tab("Progress");
  progress.focus();
  key("ArrowRight");
  expect(selected()).toBe("Work");
  expect(screen.getByRole("tab", { name: "Work" })).toHaveFocus();
  expect(progress).toHaveAttribute("tabindex", "-1");
  key("End");
  expect(selected()).toBe("About");
  key("ArrowRight");
  expect(selected()).toBe("Progress");
  key("ArrowLeft");
  expect(selected()).toBe("About");
  key("Home");
  expect(selected()).toBe("Progress");
});

test("switching tabs changes the URL and Back restores the previous tab", async () => {
  stub();
  renderPage("/tutor/students/2?group=3");
  fireEvent.click(await tab("Notes"));
  expect(screen.getByTestId("loc")).toHaveTextContent("tab=notes");
  expect(screen.getByTestId("loc")).toHaveTextContent("group=3");
  fireEvent.click(screen.getByRole("button", { name: "history back" }));
  expect(selected()).toBe("Progress");
});

test("an unsaved note survives a switch to another tab and back", async () => {
  stub();
  renderPage("/tutor/students/2?tab=notes");
  fireEvent.change(await screen.findByLabelText(/What did you notice/), {
    target: { value: "needs more practice" },
  });
  fireEvent.click(screen.getByRole("tab", { name: "About" }));
  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(screen.getByLabelText(/What did you notice/)).toHaveValue("needs more practice");
});

const DELETE = /delete/i;

test("delete lives only in About, and everything the old page offered is reachable", async () => {
  stub();
  renderPage();
  await tab("Progress");
  const where: Record<string, RegExp[]> = {
    Progress: [/Mistakes in Chemistry/],
    Work: [/^Reports$/],
    Notes: [/Starting estimate/, /Observations/, /Save estimate/, /Save observation/],
    About: [/^Name$/, /Download this student/, /^Messages$/, /Linked parents/, /Delete/],
  };
  for (const [name, patterns] of Object.entries(where)) {
    fireEvent.click(screen.getByRole("tab", { name }));
    const panel = screen.getByRole("tabpanel");
    for (const p of patterns) {
      expect((await screen.findAllByText(p, {}, { timeout: 2000 })).length).toBeGreaterThan(0);
    }
    const hasDelete = screen.queryAllByRole("button", { name: DELETE }).length > 0;
    expect(hasDelete, name).toBe(name === "About");
    expect(panel).toBeInTheDocument();
  }
});

test("a student that does not exist still says so", async () => {
  stub(404);
  renderPage();
  expect(await screen.findByText("We couldn't find that student")).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
});

test("a closed tab asks for nothing", async () => {
  stub();
  renderPage();
  await tab("Progress");
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(calls.some((c) => c.includes("observations"))).toBe(false);
  expect(calls.some((c) => c.includes("contacts"))).toBe(false);
});
