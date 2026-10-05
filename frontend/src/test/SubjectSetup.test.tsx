import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { hashTarget } from "../tutor/SectionedPage";
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
// What GET /onboarding returns; unset means the stub answers with an invalid body,
// which the app must treat as "no label" rather than a crash.
let onboarding: unknown;
let bodies: { path: string; body: unknown }[] = [];
let ackFails = false;

function stub(subjects: unknown[] = SUBJECTS) {
  requested = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      requested.push(path + url.search);
      if (path === "/api/v1/onboarding" && onboarding !== undefined) return json(onboarding);
      if (path === "/api/v1/onboarding/acknowledgements") {
        bodies.push({ path, body: JSON.parse(String(init?.body)) });
        if (ackFails) return new Response("{}", { status: 500 });
        return json(onboarding);
      }
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
  onboarding = undefined;
  bodies = [];
  ackFails = false;
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
  // The resolved subject is written back, so the URL never names one that is
  // not showing.
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent("/tutor/subject-setup?subject=7"),
  );
});

test("with no ?subject= the first subject is pinned in the URL, keeping the hash", async () => {
  // Left implicit, "the first" moves when a new syllabus sorts ahead of it.
  stub();
  renderPage("/tutor/subject-setup#marking-rules");
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/tutor/subject-setup?subject=7#marking-rules",
    ),
  );
});

test("the page says which subject its sections show", async () => {
  stub();
  renderPage("/tutor/subject-setup?subject=8");
  await screen.findByLabelText("Minimum percentage for grade 9");
  expect(screen.getByText("Showing Physics (Edexcel IGCSE 4PH1)")).toHaveAttribute(
    "role",
    "status",
  );
});

test("a malformed hash names no section instead of blanking the page", () => {
  expect(hashTarget("#%E0%A4%A")).toBe("");
  expect(hashTarget("#marking-rules")).toBe("marking-rules");
  expect(hashTarget("")).toBe("");
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

const item = (key: string, state: string, kind = "defaulted") => ({ key, kind, state });

function subjectStatus(id: number, name: string, items: ReturnType<typeof item>[]) {
  return {
    subject_id: id,
    subject_name: name,
    required: [{ key: "syllabus", done: true }],
    items,
    reviewed_count: 0,
    review_total: 4,
    classes: [],
  };
}

const ONBOARDING = {
  complete: false,
  in_flow: false,
  account: item("account_basics", "set_by_you"),
  subjects: [
    subjectStatus(7, "Chemistry", [
      item("boundaries", "not_set"),
      item("marking_rules", "default"),
      item("mistake_categories", "reviewed"),
      item("weak_threshold", "set_by_you"),
      item("teaching_guidance", "not_set", "optional"),
    ]),
    subjectStatus(8, "Physics", [
      item("boundaries", "set_by_you"),
      item("marking_rules", "set_by_you"),
      item("mistake_categories", "default"),
      item("weak_threshold", "default"),
      item("teaching_guidance", "set_by_you", "optional"),
    ]),
  ],
  next_step: null,
};

test("each section says whether its value is the default, for the selected subject", async () => {
  onboarding = ONBOARDING;
  stub();
  renderPage();
  const boundaries = await screen.findByRole("region", { name: "Grade boundaries" });
  expect(
    await within(boundaries).findByText("Not set: no predicted grades for this subject yet"),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "Marking rules" })).getByText(
      "Avora's default, not reviewed yet",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "Mistake categories" })).getByText(
      "Avora's default, kept by you",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "Preferences" })).getByText(
      "Weak-topic threshold: Set by you",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("region", { name: "Teaching guidance" })).getByText(
      "Not set (optional)",
    ),
  ).toBeInTheDocument();

  // Switching subject switches the labels.
  fireEvent.change(subjectPicker(), { target: { value: "8" } });
  const marking = screen.getByRole("region", { name: "Marking rules" });
  await waitFor(() => expect(within(marking).getByText("Set by you")).toBeInTheDocument());
  expect(
    within(screen.getByRole("region", { name: "Mistake categories" })).getByText(
      "Avora's default, not reviewed yet",
    ),
  ).toBeInTheDocument();
});

test("no label shows when the onboarding read has not answered with a valid state", async () => {
  stub();
  renderPage();
  const marking = await screen.findByRole("region", { name: "Marking rules" });
  await screen.findByLabelText(/Marking rules for Chemistry/);
  expect(within(marking).queryByText("Avora's default, not reviewed yet")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Keep the default/ })).not.toBeInTheDocument();
});

test("a default offers Keep the default, which acknowledges that item for that subject", async () => {
  onboarding = ONBOARDING;
  stub();
  renderPage();
  const keep = await screen.findByRole("button", {
    name: "Keep the default for Marking rules, Chemistry",
  });
  // Boundaries are not_set: there is no default in force to keep.
  expect(screen.getAllByRole("button", { name: /Keep the default/ })).toHaveLength(1);
  fireEvent.click(keep);
  await waitFor(() =>
    expect(bodies).toEqual([
      {
        path: "/api/v1/onboarding/acknowledgements",
        body: { item: "marking_rules", subject_id: 7 },
      },
    ]),
  );
});

test("saving marking rules refetches the onboarding state", async () => {
  onboarding = ONBOARDING;
  stub();
  renderPage();
  const marking = await screen.findByRole("region", { name: "Marking rules" });
  const box = await within(marking).findByLabelText(/Marking rules for Chemistry/);
  await within(marking).findByText("Avora's default, not reviewed yet");
  const reads = () => requested.filter((r) => r === "/api/v1/onboarding").length;
  // Let the labels' own mount-time reads settle, so only the save moves the count.
  await new Promise((r) => setTimeout(r, 50));
  const before = reads();
  fireEvent.change(box, { target: { value: "Always show units" } });
  fireEvent.click(within(marking).getByRole("button", { name: /^Save/ }));
  await waitFor(() => expect(reads()).toBeGreaterThan(before));
});

test("a failed Keep the default shows its error on the pressed label only", async () => {
  onboarding = ONBOARDING;
  ackFails = true;
  stub();
  renderPage("/tutor/subject-setup?subject=8");
  // Physics has two defaults: mistake categories and the weak-topic threshold.
  fireEvent.click(
    await screen.findByRole("button", { name: "Keep the default for Mistake categories, Physics" }),
  );
  const mistakes = screen.getByRole("region", { name: "Mistake categories" });
  expect(await within(mistakes).findByRole("alert")).toHaveTextContent(/went wrong/i);
  expect(
    within(screen.getByRole("region", { name: "Preferences" })).queryByRole("alert"),
  ).not.toBeInTheDocument();
  // The button stays in the tab order and usable for a retry.
  expect(
    screen.getByRole("button", { name: "Keep the default for Mistake categories, Physics" }),
  ).not.toBeDisabled();
});
