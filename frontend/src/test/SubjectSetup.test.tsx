import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import SubjectSetupPage from "../tutor/SubjectSetupPage";

/* Subject setup (9.3a): everything that belongs to a subject, with the subject
   chosen once at the top. */

const state = vi.hoisted(() => ({ broken: false }));
vi.mock("../tutor/MarkingRulesPage", async (importOriginal) => {
  const real = await importOriginal<typeof import("../tutor/MarkingRulesPage")>();
  return {
    default: () => {
      if (state.broken) throw new Error("boom");
      return <real.default />;
    },
  };
});

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
  { id: 8, exam_board: "Edexcel IGCSE", code: "4PH1", name: "Physics", grade_scale: "9-1" },
];

const FACTORS = [
  "topic_mastery",
  "past_paper_performance",
  "homework_performance",
  "assessment_performance",
  "syllabus_coverage",
  "mistake_analysis",
];

let requested: string[] = [];

function stub(subjects: unknown[] = SUBJECTS) {
  requested = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      requested.push(path + url.search);
      if (path === "/api/v1/auth/me")
        return json({ id: 1, email: "t@example.com", username: null, role: "tutor", name: "T" });
      if (path === "/api/v1/subjects") return json(subjects);
      const m = /^\/api\/v1\/subjects\/(\d+)\/(.+)$/.exec(path);
      if (m) {
        const id = Number(m[1]);
        const name = id === 7 ? "Chemistry" : "Physics";
        const base = { subject_id: id, subject_name: name };
        if (m[2] === "grade-boundaries")
          return json({
            ...base,
            grade_scale: "9-1",
            source: "organization",
            boundaries: [
              { grade: "9", min: 90 },
              { grade: "8", min: 80 },
            ],
          });
        if (m[2] === "teaching-guidance") return json({ ...base, uploaded: false });
        if (m[2] === "marking-rules")
          return json({ ...base, rules: "", configured: false, summary: null });
        if (m[2] === "mistake-categories")
          return json({ ...base, source: "organization", categories: [] });
      }
      if (path === "/api/v1/readiness/weights")
        return json({
          ...Object.fromEntries(FACTORS.map((f) => [`weight_${f}`, 1])),
          ...Object.fromEntries(FACTORS.map((f) => [`enabled_${f}`, true])),
          half_life_days: 45,
          weak_threshold: 60,
          subject_id: url.searchParams.get("subject_id")
            ? Number(url.searchParams.get("subject_id"))
            : null,
          source: "default",
        });
      return json([]);
    }),
  );
}

function Where() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="where">{pathname + search + hash}</output>;
}

function renderPage(entry = "/tutor/subject-setup") {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[entry]}>
        <SubjectSetupPage />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderApp(entry: string) {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[entry]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const subjectPicker = () => screen.getByRole("combobox", { name: "Subject" });

beforeEach(() => {
  state.broken = false;
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("the six sections render in order, each under its heading", async () => {
  stub();
  renderPage();
  await screen.findByRole("heading", { level: 1, name: "Subject setup" });
  const wanted = [
    "Syllabus",
    "Grade boundaries",
    "Teaching guidance",
    "Marking rules",
    "Mistake categories",
    "Preferences",
  ];
  await waitFor(() =>
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(wanted),
  );
  const ids = wanted.map((w) => screen.getByRole("region", { name: w }).id);
  expect(ids).toEqual([
    "syllabus",
    "boundaries",
    "teaching-guidance",
    "marking-rules",
    "mistake-categories",
    "preferences",
  ]);
  const index = screen.getByRole("navigation", { name: "Subject setup sections" });
  expect(within(index).getAllByRole("link")).toHaveLength(6);
});

test("there is one Subject picker, at the top, and none inside the sections", async () => {
  stub();
  renderPage();
  await screen.findByRole("region", { name: "Preferences" });
  await screen.findByLabelText("Minimum percentage for grade 9");
  expect(screen.getAllByRole("combobox", { name: "Subject" })).toHaveLength(1);
  expect(screen.queryByRole("combobox", { name: "Settings for" })).not.toBeInTheDocument();
  for (const name of ["Grade boundaries", "Teaching guidance", "Marking rules", "Preferences"]) {
    expect(within(screen.getByRole("region", { name })).queryByRole("combobox")).toBeNull();
  }
});

test("choosing a subject updates ?subject= and every section asks for that subject", async () => {
  stub();
  renderPage("/tutor/subject-setup#marking-rules");
  await screen.findByLabelText("Minimum percentage for grade 9");
  expect(requested).toContain("/api/v1/subjects/7/grade-boundaries");

  fireEvent.change(subjectPicker(), { target: { value: "8" } });

  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/tutor/subject-setup?subject=8#marking-rules",
    ),
  );
  await waitFor(() => {
    for (const section of [
      "grade-boundaries",
      "teaching-guidance",
      "marking-rules",
      "mistake-categories",
    ])
      expect(requested).toContain(`/api/v1/subjects/8/${section}`);
    expect(requested).toContain("/api/v1/readiness/weights?subject_id=8");
  });
});

test("an unsaved draft is not carried from one subject to the next", async () => {
  stub();
  renderPage();
  const nine = await screen.findByLabelText("Minimum percentage for grade 9");
  fireEvent.change(nine, { target: { value: "55" } });
  expect(screen.getByLabelText<HTMLInputElement>("Minimum percentage for grade 9").value).toBe(
    "55",
  );

  fireEvent.change(subjectPicker(), { target: { value: "8" } });
  await waitFor(() =>
    expect(screen.getByLabelText<HTMLInputElement>("Minimum percentage for grade 9").value).toBe(
      "90",
    ),
  );
});

test("?subject=<id> selects that subject, and an unknown id falls back to the first", async () => {
  stub();
  const first = renderPage("/tutor/subject-setup?subject=8");
  await screen.findByLabelText("Minimum percentage for grade 9");
  expect((subjectPicker() as HTMLSelectElement).value).toBe("8");
  expect(requested).toContain("/api/v1/subjects/8/grade-boundaries");
  first.unmount();

  stub();
  renderPage("/tutor/subject-setup?subject=999");
  await screen.findByLabelText("Minimum percentage for grade 9");
  expect((subjectPicker() as HTMLSelectElement).value).toBe("7");
  expect(requested).not.toContain("/api/v1/subjects/999/grade-boundaries");
});

test("the account-wide readiness settings stay reachable without a second picker", async () => {
  stub();
  renderPage();
  // Wait for the subject's own settings: the section remounts once the subject
  // list resolves, and a click on the earlier button would land on a dead node.
  await screen.findByText(/Using the built-in defaults/);
  const prefs = screen.getByRole("region", { name: "Preferences" });
  fireEvent.click(
    within(prefs).getByRole("button", { name: "Edit the settings for all subjects" }),
  );
  await waitFor(() => expect(requested).toContain("/api/v1/readiness/weights"));
  fireEvent.click(await within(prefs).findByRole("button", { name: "Back to this subject" }));
  expect(within(prefs).getByText("this subject")).toBeInTheDocument();
});

test("with no subjects there is one empty state, and the Syllabus section still renders", async () => {
  stub([]);
  renderPage();
  expect(await screen.findAllByText("No subjects yet.")).toHaveLength(1);
  expect(screen.getByRole("region", { name: "Syllabus" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Grade boundaries" })).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Subject" })).not.toBeInTheDocument();
});

test("/tutor/settings#boundaries and /tutor/boundaries both land on Subject setup's boundaries", async () => {
  for (const entry of ["/tutor/settings#boundaries", "/tutor/boundaries"]) {
    stub();
    const { unmount } = renderApp(entry);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Subject setup" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Grade boundaries" })).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement?.id).toBe("boundaries"));
    unmount();
    localStorage.clear();
  }
});

test("a moved Settings hash keeps ?subject= when it is forwarded", async () => {
  stub();
  renderApp("/tutor/settings?subject=8#preferences");
  await screen.findByRole("heading", { level: 1, name: "Subject setup" });
  await waitFor(() => expect((subjectPicker() as HTMLSelectElement).value).toBe("8"));
});

test("Settings shows only Messages and Account and integrations", async () => {
  stub();
  renderApp("/tutor/settings");
  await screen.findByRole("heading", { level: 1, name: "Settings" });
  expect(screen.getAllByRole("region").map((r) => r.id)).toEqual(["messages", "account"]);
});

test("one section throwing does not take the others down, and retries alone", async () => {
  stub();
  vi.spyOn(console, "error").mockImplementation(() => {});
  state.broken = true;
  renderPage();
  const broken = await screen.findByRole("region", { name: "Marking rules" });
  expect(within(broken).getByText("This section didn't load")).toBeInTheDocument();
  expect(await screen.findByLabelText("Minimum percentage for grade 9")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Preferences" })).toBeInTheDocument();

  state.broken = false;
  fireEvent.click(within(broken).getByRole("button", { name: /Try again/ }));
  expect(await within(broken).findByLabelText(/Marking rules for Chemistry/)).toBeInTheDocument();
});
