import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

/* The tutor's home as the setup flow (9.1c). The server says where the tutor is
   (`in_flow`, `next_step`, each step's `done`); these tests give it payloads and
   check what is opened, locked, announced and posted. */

const item = (key: string, state: string, kind = "defaulted") => ({ key, kind, state });
const step = (key: string, done: boolean) => ({ key, done });
const classSteps = (done: string[]) =>
  ["timetable", "taught_before", "plan_inputs", "plan_accepted"].map((k) =>
    step(k, done.includes(k)),
  );

function subject(over: Record<string, unknown> = {}) {
  return {
    subject_id: 7,
    subject_name: "Chemistry",
    required: [{ key: "syllabus", done: true }],
    items: [
      item("boundaries", "not_set"),
      item("marking_rules", "default"),
      item("mistake_categories", "default"),
      item("weak_threshold", "default"),
      item("teaching_guidance", "not_set", "optional"),
    ],
    reviewed_count: 0,
    review_total: 4,
    classes: [],
    ...over,
  };
}

const withClass = (done: string[]) =>
  subject({
    classes: [{ group_id: 11, group_name: "Chem A", steps: classSteps(done), complete: false }],
  });

function state(over: Record<string, unknown> = {}) {
  return {
    complete: false,
    in_flow: true,
    account: item("account_basics", "default"),
    subjects: [],
    next_step: { key: "syllabus", subject_id: null, group_id: null },
    ...over,
  };
}

const next = (key: string, subjectId: number | null = 7, groupId: number | null = null) => ({
  key,
  subject_id: subjectId,
  group_id: groupId,
});

let onboarding: unknown;
let onboardingFails = false;
let classCount = 0;
let calls: { method: string; path: string; body: unknown }[] = [];
let boundaries: { source: string; boundaries: { grade: string; min: number }[] };
let client: QueryClient;

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      const method = init?.method ?? "GET";
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (method !== "GET") {
        calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
      }
      if (path.includes("/auth/me"))
        return json({ id: 1, email: "t@example.com", username: null, role: "tutor", name: "T" });
      if (path === "/api/v1/onboarding/acknowledgements") return json(onboarding);
      if (path === "/api/v1/onboarding") {
        if (onboardingFails) return new Response("{}", { status: 500 });
        return json(onboarding);
      }
      if (path === "/api/v1/today/overview") return new Response("{}", { status: 500 });
      if (path === "/api/v1/today")
        return json({
          classes: [],
          lessons: [],
          review_count: 0,
          class_count: classCount,
          joined_student_count: 0,
          classes_with_evidence: 0,
        });
      if (path === "/api/v1/subjects")
        return json([
          { id: 7, name: "Chemistry", exam_board: "Edexcel", code: "4CH1", grade_scale: "9-1" },
        ]);
      if (path === "/api/v1/subjects/7/grade-boundaries") {
        if (method === "PUT") {
          boundaries = {
            source: "organization",
            boundaries: JSON.parse(String(init?.body)).boundaries,
          };
        }
        return json({
          subject_id: 7,
          subject_name: "Chemistry",
          grade_scale: "9-1",
          ...boundaries,
        });
      }
      if (path === "/api/v1/groups" && method === "POST") return json({ id: 11 });
      if (path === "/api/v1/groups/11/plan")
        return json({
          draft: null,
          accepted: null,
          timetable_defaults: { lessons_per_week: null, lesson_minutes: null },
        });
      return json([]);
    }),
  );
}

function renderApp() {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  onboarding = state();
  onboardingFails = false;
  classCount = 0;
  calls = [];
  boundaries = {
    source: "none",
    boundaries: [
      { grade: "9", min: 80 },
      { grade: "8", min: 70 },
    ],
  };
  stub();
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

const STEP_NUMBER = {
  account: 1,
  syllabus: 2,
  boundaries: 3,
  defaults: 4,
  guidance: 5,
  timetable: 6,
  taught_before: 7,
  plan_inputs: 8,
  plan_accepted: 9,
} as const;

/** A step's h2, found by id: its visible number is hidden from the accessible name. */
async function stepHeading(id: keyof typeof STEP_NUMBER) {
  // Either title: "Finish setting up" is the same guide for a tutor with a class.
  await screen.findByRole("heading", {
    level: 1,
    name: /^(Set up your first class|Finish setting up)$/,
  });
  return document.getElementById(`onboarding-step-${id}`)!;
}

/** The disclosure button inside a step's heading. */
async function stepButton(id: keyof typeof STEP_NUMBER) {
  const heading = await stepHeading(id);
  return within(heading).getByRole("button");
}

async function openSteps() {
  const open: string[] = [];
  for (const id of Object.keys(STEP_NUMBER) as (keyof typeof STEP_NUMBER)[]) {
    if ((await stepButton(id)).getAttribute("aria-expanded") === "true") open.push(id);
  }
  return open;
}

test("in_flow renders the flow and not the dashboard or the checklist card", async () => {
  renderApp();
  expect(
    await screen.findByRole("heading", { level: 1, name: "Set up your first class" }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.queryByRole("region", { name: "Setup" })).not.toBeInTheDocument();
  expect(screen.getByRole("list", { name: "" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThanOrEqual(9);
});

test("a tutor in the flow who already has a class keeps the dashboard under the guide", async () => {
  classCount = 1;
  onboarding = state({ subjects: [withClass([])], next_step: next("timetable", 7, 11) });
  renderApp();
  expect(
    await screen.findByRole("heading", { level: 1, name: "Finish setting up" }),
  ).toBeInTheDocument();
  // The dashboard is there and usable: its way to schedule a lesson, and its
  // verdict as a section heading so the page still has one h1.
  expect(await screen.findByRole("button", { name: /Schedule a lesson/ })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(document.getElementById("overview-verdict")?.tagName).toBe("H2");
  // The guide is the setup path here; the checklist card would say it twice.
  expect(screen.queryByRole("region", { name: "Setup" })).not.toBeInTheDocument();
  expect(screen.getByText(/Your overview is below and keeps working/)).toBeInTheDocument();
});

test("a tutor in the flow with no class gets the guide alone", async () => {
  renderApp();
  await screen.findByRole("heading", { level: 1, name: "Set up your first class" });
  expect(screen.queryByRole("button", { name: /Schedule a lesson/ })).not.toBeInTheDocument();
  expect(calls).toEqual([]);
});

test("a tutor out of the flow gets the dashboard and the checklist card", async () => {
  classCount = 1;
  onboarding = state({ in_flow: false });
  renderApp();
  expect(await screen.findByRole("region", { name: "Setup" })).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Set up your first class" }),
  ).not.toBeInTheDocument();
});

test.each([
  ["syllabus", state(), "syllabus"],
  ["timetable", state({ subjects: [subject()], next_step: next("timetable") }), "timetable"],
  [
    "timetable with a class",
    state({ subjects: [withClass([])], next_step: next("timetable", 7, 11) }),
    "timetable",
  ],
  [
    "taught_before",
    state({ subjects: [withClass(["timetable"])], next_step: next("taught_before", 7, 11) }),
    "taught_before",
  ],
  [
    "plan_inputs",
    state({
      subjects: [withClass(["timetable", "taught_before"])],
      next_step: next("plan_inputs", 7, 11),
    }),
    "plan_inputs",
  ],
  [
    "plan_accepted",
    state({
      subjects: [withClass(["timetable", "taught_before", "plan_inputs"])],
      next_step: next("plan_accepted", 7, 11),
    }),
    "plan_accepted",
  ],
])("the open step is the server's next_step: %s", async (_name, payload, expected) => {
  onboarding = payload;
  renderApp();
  await stepButton("account");
  await waitFor(async () => expect(await openSteps()).toEqual([expected]));
});

test("a required step whose earlier step is undone is shown, says what it needs, and does not open", async () => {
  renderApp();
  const button = await stepButton("timetable");
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).toHaveAccessibleDescription("Add the syllabus first");
  fireEvent.click(button);
  expect(button).not.toHaveAttribute("aria-expanded");
  expect(await openSteps()).toEqual(["syllabus"]);
  // Later class steps wait on the class, not on the syllabus.
  expect(await stepButton("plan_accepted")).toHaveAccessibleDescription(
    "Enter the plan details first",
  );
});

test("every step carries its marker as text", async () => {
  renderApp();
  const markers = [
    ["account", "Can wait"],
    ["syllabus", "Required"],
    ["boundaries", "Can wait"],
    ["defaults", "Can wait"],
    ["guidance", "Optional"],
    ["timetable", "Required"],
  ] as const;
  for (const [id, marker] of markers) {
    expect(within(await stepHeading(id)).getByText(marker)).toBeInTheDocument();
  }
});

test("a done step can be reopened, and the server's step closes", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  const syllabus = await stepButton("syllabus");
  expect(syllabus).toHaveTextContent("Done");
  fireEvent.click(syllabus);
  await waitFor(async () => expect(await openSteps()).toEqual(["syllabus"]));
});

test("defaulted rows show the server's wording, and Keep the default posts the acknowledgement", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("defaults"));
  const panel = document.getElementById("onboarding-step-defaults-panel")!;
  expect(await within(panel).findAllByText("Avora's default, not reviewed yet")).toHaveLength(3);
  expect(await stepButton("defaults")).toHaveTextContent("0 of 3 reviewed");
  fireEvent.click(
    screen.getByRole("button", { name: "Keep the default for Marking rules, Chemistry" }),
  );
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: "POST",
      path: "/api/v1/onboarding/acknowledgements",
      body: { item: "marking_rules", subject_id: 7 },
    }),
  );
  expect(screen.getAllByRole("link", { name: /^Change / })[0]).toHaveAttribute(
    "href",
    "/tutor/subject-setup?subject=7#marking-rules",
  );
});

test("account basics shows the server's state and keeps the defaults on request", async () => {
  renderApp();
  fireEvent.click(await stepButton("account"));
  fireEvent.click(
    await screen.findByRole("button", { name: "Keep the defaults for account settings" }),
  );
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: "POST",
      path: "/api/v1/onboarding/acknowledgements",
      body: { item: "account_basics", subject_id: null },
    }),
  );
});

test("the boundaries button reads Use the standard boundaries for now only while nothing is saved and the values are the published ones", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  expect(
    await screen.findByText(/Nothing is saved until you choose to use them or enter your own/),
  ).toBeInTheDocument();
  const useThese = await screen.findByRole("button", {
    name: "Use the standard boundaries for now",
  });
  // Editing a value is a choice of the tutor's own: the plain label returns.
  fireEvent.change(screen.getByLabelText("Minimum percentage for grade 9"), {
    target: { value: "85" },
  });
  expect(
    screen.queryByRole("button", { name: "Use the standard boundaries for now" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Minimum percentage for grade 9"), {
    target: { value: "80" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Use the standard boundaries for now" }),
  );
  expect(useThese).toBeDefined();
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: "PUT",
      path: "/api/v1/subjects/7/grade-boundaries",
      body: {
        boundaries: [
          { grade: "9", min: 80 },
          { grade: "8", min: 70 },
        ],
      },
    }),
  );
  // Saved boundaries are the organization's own now: back to the plain label.
  expect(await screen.findByRole("button", { name: "Save boundaries" })).toBeInTheDocument();
});

test("creating the class posts the name with the flow's subject", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.change(await screen.findByLabelText(/Class name/), { target: { value: "Chem A" } });
  fireEvent.click(screen.getByRole("button", { name: "Create class" }));
  await waitFor(() =>
    expect(calls).toContainEqual({
      method: "POST",
      path: "/api/v1/groups",
      body: { name: "Chem A", subject_id: 7 },
    }),
  );
});

test("a failed onboarding read falls back to the plain dashboard", async () => {
  onboardingFails = true;
  renderApp();
  expect(await screen.findByText("No classes yet.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open Subject setup" })).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Set up your first class" }),
  ).not.toBeInTheDocument();
});

test("accepting the plan hands the home to the dashboard, with a line for that visit", async () => {
  onboarding = state({
    subjects: [withClass(["timetable", "taught_before", "plan_inputs"])],
    next_step: next("plan_accepted", 7, 11),
  });
  renderApp();
  await stepButton("plan_accepted");
  classCount = 1;
  onboarding = state({
    in_flow: false,
    complete: true,
    next_step: null,
    subjects: [
      subject({
        classes: [
          {
            group_id: 11,
            group_name: "Chem A",
            steps: classSteps(["timetable", "taught_before", "plan_inputs", "plan_accepted"]),
            complete: true,
          },
        ],
      }),
    ],
  });
  // What the accept mutation invalidates: the onboarding state and the home aggregate.
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
    await client.invalidateQueries({ queryKey: ["today"] });
  });
  expect(
    await screen.findByText(
      /Your teaching plan is accepted\. Students can be added from the class page\./,
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Students tab for Chem A/ })).toHaveAttribute(
    "href",
    "/tutor/groups/11/students",
  );
  expect(
    screen.queryByRole("heading", { name: "Set up your first class" }),
  ).not.toBeInTheDocument();
});

test("a later visit to the dashboard has no accepted line", async () => {
  classCount = 1;
  onboarding = state({ in_flow: false, complete: true, next_step: null, subjects: [subject()] });
  renderApp();
  await screen.findByRole("region", { name: "Setup" });
  expect(screen.queryByText(/Your teaching plan is accepted/)).not.toBeInTheDocument();
});

test("moving to the next step announces it once and moves focus to its heading", async () => {
  renderApp();
  await stepButton("syllabus");
  const status = screen.getAllByRole("status").find((el) => el.className.includes("sr-only"))!;
  expect(status).toHaveTextContent("");
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  await waitFor(() =>
    expect(status).toHaveTextContent("Syllabus done. Next: Class and timetable."),
  );
  expect(document.activeElement).toBe(document.getElementById("onboarding-step-timetable"));
  expect(await openSteps()).toEqual(["timetable"]);
});

/* --- review fixes: keeping the tutor's work and place ------------------------ */

const PLAN_FLOW = () =>
  state({
    subjects: [withClass(["timetable", "taught_before"])],
    next_step: next("plan_inputs", 7, 11),
  });

test("a refetch with an unchanged next_step keeps what the tutor typed (boundaries draft)", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  const field = await screen.findByLabelText("Minimum percentage for grade 9");
  fireEvent.change(field, { target: { value: "85" } });
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  expect(await screen.findByLabelText("Minimum percentage for grade 9")).toHaveValue(85);
});

test("a refetch with an unchanged next_step keeps what the tutor typed (plan input)", async () => {
  onboarding = PLAN_FLOW();
  renderApp();
  const exam = await screen.findByLabelText(/Exam date/);
  fireEvent.change(exam, { target: { value: "2027-05-01" } });
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  expect(await screen.findByLabelText(/Exam date/)).toHaveValue("2027-05-01");
  expect(screen.getByRole("button", { name: "Save plan inputs" })).toHaveAccessibleDescription(
    "Exam date, lessons a week and lesson length are needed to draft a plan.",
  );
});

test("a step opened by hand stays open with its input when the server moves on", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  const field = await screen.findByLabelText("Minimum percentage for grade 9");
  field.focus();
  fireEvent.change(field, { target: { value: "85" } });
  const status = screen.getAllByRole("status").find((el) => el.className.includes("sr-only"))!;

  onboarding = state({
    subjects: [withClass([])],
    next_step: next("timetable", 7, 11),
  });
  // The class now exists but the next step is still the timetable: no move.
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  expect(status).toHaveTextContent("");

  onboarding = state({
    subjects: [withClass(["timetable"])],
    next_step: next("taught_before", 7, 11),
  });
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  await waitFor(() =>
    expect(status).toHaveTextContent("Class and timetable done. Next: Where this class is up to."),
  );
  // The boundaries step and the typed value are still there, and focus stayed.
  expect(await openSteps()).toEqual(["boundaries"]);
  expect(screen.getByLabelText("Minimum percentage for grade 9")).toHaveValue(85);
  expect(document.activeElement).toBe(screen.getByLabelText("Minimum percentage for grade 9"));
});

test("focus follows when it was inside the step that completed", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  const name = await screen.findByLabelText(/Class name/);
  name.focus();
  onboarding = state({
    subjects: [withClass(["timetable"])],
    next_step: next("taught_before", 7, 11),
  });
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  await waitFor(() =>
    expect(document.activeElement).toBe(document.getElementById("onboarding-step-taught_before")),
  );
});

test("creating a class twice sends one request, and a blank name sends none", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  const create = await screen.findByRole("button", { name: "Create class" });
  fireEvent.change(screen.getByLabelText(/Class name/), { target: { value: "   " } });
  fireEvent.click(create);
  expect(await screen.findByText("Give the class a name.")).toBeInTheDocument();
  expect(calls.filter((c) => c.path === "/api/v1/groups")).toHaveLength(0);

  fireEvent.change(screen.getByLabelText(/Class name/), { target: { value: "Chem A" } });
  fireEvent.click(create);
  fireEvent.click(create);
  fireEvent.submit(create.closest("form")!);
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/v1/groups")).toHaveLength(1));
  await waitFor(() => expect(screen.getByLabelText(/Class name/)).toHaveValue(""));
  expect(screen.getByRole("button", { name: "Create class" })).toBeDisabled();
});

test("a failed refetch mid-flow keeps the flow on screen", async () => {
  renderApp();
  await stepButton("syllabus");
  onboardingFails = true;
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["onboarding"] });
  });
  expect(
    screen.getByRole("heading", { level: 1, name: "Set up your first class" }),
  ).toBeInTheDocument();
  expect(await openSteps()).toEqual(["syllabus"]);
});

test("two subjects mid-setup follow next_step and name the right subject and class", async () => {
  onboarding = state({
    subjects: [
      subject({ subject_id: 3, subject_name: "Physics", classes: [] }),
      {
        ...subject(),
        classes: [
          { group_id: 11, group_name: "Chem A", steps: classSteps(["timetable"]), complete: false },
        ],
      },
    ],
    next_step: next("taught_before", 7, 11),
  });
  renderApp();
  expect(await openSteps()).toEqual(["taught_before"]);
  expect(within(await stepHeading("taught_before")).getByRole("button")).toHaveTextContent(
    "Chem A",
  );
  expect(within(await stepHeading("timetable")).getByRole("button")).toHaveTextContent("Chemistry");
  expect(within(await stepHeading("timetable")).getByRole("button")).not.toHaveTextContent(
    "Physics",
  );
});

test("with no subjects the syllabus step is the open one", async () => {
  renderApp();
  await stepButton("syllabus");
  expect(await openSteps()).toEqual(["syllabus"]);
});

test("a locked step has no aria-expanded or aria-controls, and its number is hidden", async () => {
  renderApp();
  const button = await stepButton("timetable");
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).not.toHaveAttribute("aria-expanded");
  expect(button).not.toHaveAttribute("aria-controls");
  expect(button.querySelector("[aria-hidden]")).toHaveTextContent("6.");
});

test("an open embedded step has no second heading carrying the step's own name", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  await screen.findByLabelText("Minimum percentage for grade 9");
  const named = screen
    .getAllByRole("heading")
    .filter((h) => h.textContent?.includes("Grade boundaries"));
  expect(named).toHaveLength(1);
  expect(named[0].tagName).toBe("H2");
  fireEvent.click(await stepButton("syllabus"));
  const syllabus = screen.getAllByRole("heading").filter((h) => h.textContent === "Syllabus");
  expect(syllabus).toEqual([]);
});

test("the standard-boundaries sentence is tied to the button", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  const button = await screen.findByRole("button", { name: "Use the standard boundaries for now" });
  expect(button).toHaveAccessibleDescription(/Nothing is saved until you choose to use them/);
});

test("the dashboard's own reads start with the page and are not repeated once the flow is known", async () => {
  const paths = () =>
    (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.map(
      (c) => new URL(String(c[0]), "http://localhost").pathname,
    );
  const own = ["/api/v1/today", "/api/v1/today/overview", "/api/v1/groups"];
  renderApp();
  await stepButton("syllabus");
  // Asked for once, alongside the onboarding read, so the dashboard is never
  // held behind it; then left alone, because nothing in the flow shows them.
  await screen.findByRole("heading", { level: 1 });
  await new Promise((r) => setTimeout(r, 50));
  for (const path of own) {
    expect(paths().filter((p) => p === path).length).toBeLessThanOrEqual(1);
  }
  cleanup();

  classCount = 1;
  onboarding = state({ in_flow: false });
  stub();
  renderApp();
  await screen.findByRole("region", { name: "Setup" });
  expect(paths()).toContain("/api/v1/today");
  expect(paths()).toContain("/api/v1/today/overview");
});

test("a failed onboarding read still reaches the dashboard, whose Setup card retries it without a loop", async () => {
  onboardingFails = true;
  classCount = 1;
  renderApp();
  await screen.findByText(/Setup checklist couldn't be loaded/);
  const onboardingCalls = () =>
    (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.filter((c) =>
      String(c[0]).endsWith("/api/v1/onboarding"),
    ).length;
  const settled = onboardingCalls();
  await new Promise((r) => setTimeout(r, 300));
  expect(onboardingCalls()).toBe(settled);
  expect(
    screen.queryByRole("heading", { name: "Set up your first class" }),
  ).not.toBeInTheDocument();
});
