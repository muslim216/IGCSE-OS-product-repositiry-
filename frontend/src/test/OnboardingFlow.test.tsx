import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

/** The disclosure button inside a step's heading. */
async function stepButton(id: keyof typeof STEP_NUMBER) {
  const heading = await screen.findByRole("heading", {
    level: 2,
    name: new RegExp(`^${STEP_NUMBER[id]}\\.`),
  });
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
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(await openSteps()).toEqual(["syllabus"]);
  // Later class steps wait on the class, not on the syllabus.
  expect(await stepButton("plan_accepted")).toHaveAccessibleDescription(
    "Enter the plan details first",
  );
});

test("every step carries its marker as text", async () => {
  renderApp();
  const markers = ["Can wait", "Required", "Can wait", "Can wait", "Optional", "Required"];
  for (const [i, marker] of markers.entries()) {
    const heading = await screen.findByRole("heading", {
      level: 2,
      name: new RegExp(`^${i + 1}\\.`),
    });
    expect(within(heading).getByText(marker)).toBeInTheDocument();
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

test("the boundaries button reads Use these for now only while nothing is saved and the values are the published ones", async () => {
  onboarding = state({ subjects: [subject()], next_step: next("timetable") });
  renderApp();
  fireEvent.click(await stepButton("boundaries"));
  expect(
    await screen.findByText(/Nothing is saved until you press the button below/),
  ).toBeInTheDocument();
  const useThese = await screen.findByRole("button", { name: "Use these for now" });
  // Editing a value is a choice of the tutor's own: the plain label returns.
  fireEvent.change(screen.getByLabelText("Minimum percentage for grade 9"), {
    target: { value: "85" },
  });
  expect(screen.queryByRole("button", { name: "Use these for now" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Minimum percentage for grade 9"), {
    target: { value: "80" },
  });
  fireEvent.click(await screen.findByRole("button", { name: "Use these for now" }));
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
  fireEvent.change(await screen.findByLabelText("Class name"), { target: { value: "Chem A" } });
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
