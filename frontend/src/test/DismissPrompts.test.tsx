import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

/* "Not now" on what the tutor's home asks of them (owner decision 2026-10-06).
   The server is faked as a set of hidden keys so a hide, a refusal and a restore
   can each be seen from the page. */

const item = (key: string, state: string, kind = "defaulted") => ({ key, kind, state });
const allDone = ["timetable", "taught_before", "plan_inputs", "plan_accepted"].map((key) => ({
  key,
  done: true,
}));

function subject(over: Record<string, unknown> = {}) {
  return {
    subject_id: 7,
    subject_name: "Chemistry",
    required: [{ key: "syllabus", done: true }],
    items: [
      item("boundaries", "not_set"),
      item("marking_rules", "set_by_you"),
      item("mistake_categories", "set_by_you"),
      item("weak_threshold", "set_by_you"),
      item("teaching_guidance", "set_by_you", "optional"),
    ],
    reviewed_count: 3,
    review_total: 4,
    classes: [{ group_id: 1, group_name: "Chem A", steps: allDone, complete: true }],
    ...over,
  };
}

function state(over: Record<string, unknown> = {}) {
  return {
    complete: false,
    in_flow: false,
    account: item("account_basics", "set_by_you"),
    subjects: [subject()],
    next_step: null,
    ...over,
  };
}

const PROMPT = {
  group_id: 3,
  group_name: "Year 11 Chemistry",
  subject_name: "Chemistry",
  chapter_id: 9,
  chapter_code: "4",
  chapter_title: "Organic chemistry",
  starts_on: "2026-10-01",
  ends_on: "2026-10-20",
  started: true,
};

let onboarding: unknown;
let todayExtra: Record<string, unknown>;
let attention: unknown[];
let hidden: Set<string>;
let failPut: boolean;
let calls: { method: string; path: string }[];

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = decodeURIComponent(new URL(String(input), "http://localhost").pathname);
      const method = init?.method ?? "GET";
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const gone = () => new Response(null, { status: 204 });
      if (path.includes("/auth/me"))
        return json({ id: 1, email: "t@example.com", username: null, role: "tutor", name: "T" });
      if (path.startsWith("/api/v1/me/dismissals")) {
        if (method !== "GET") calls.push({ method, path });
        if (method === "GET") return json({ keys: [...hidden] });
        if (method === "PUT") {
          if (failPut) return new Response(JSON.stringify({ detail: "Nope" }), { status: 500 });
          hidden.add(path.split("/dismissals/")[1]);
          return gone();
        }
        if (path === "/api/v1/me/dismissals") hidden.clear();
        else hidden.delete(path.split("/dismissals/")[1]);
        return gone();
      }
      if (path === "/api/v1/onboarding") return json(onboarding);
      if (path === "/api/v1/today/overview") return new Response("{}", { status: 500 });
      if (path === "/api/v1/today/reminders") return json([]);
      if (path === "/api/v1/today")
        return json({
          classes: [],
          lessons: [],
          review_count: 0,
          class_count: 1,
          joined_student_count: 0,
          classes_with_evidence: 0,
          ...todayExtra,
        });
      if (path === "/api/v1/assignments/attention") return json(attention);
      return json([]);
    }),
  );
}

function renderApp() {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
  render(
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
  onboarding = state();
  todayExtra = {};
  attention = [];
  hidden = new Set();
  failPut = false;
  calls = [];
  stub();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

const BOUNDARIES_LINE = "Not now: Set boundaries for Chemistry";

test("hiding a checklist line removes it, saves it, and Show hidden brings it back", async () => {
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: BOUNDARIES_LINE }));

  await waitFor(() =>
    expect(screen.queryByRole("link", { name: "Set boundaries for Chemistry" })).toBeNull(),
  );
  expect(calls).toEqual([
    { method: "PUT", path: "/api/v1/me/dismissals/setup_checklist:7:boundaries" },
  ]);
  // Said politely, and the way back is named.
  expect(
    screen.getByText("Hidden. You can bring it back from the bottom of this page."),
  ).toBeInTheDocument();
  expect(await screen.findByText("1 hidden")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Show hidden" }));
  expect(
    await screen.findByRole("link", { name: "Set boundaries for Chemistry" }),
  ).toBeInTheDocument();
  expect(calls[1]).toEqual({ method: "DELETE", path: "/api/v1/me/dismissals" });
  expect(screen.queryByText(/ hidden$/)).toBeNull();
});

test("nothing is hidden and no footer shows when nothing has been hidden", async () => {
  renderApp();
  await screen.findByRole("button", { name: BOUNDARIES_LINE });
  expect(screen.queryByRole("button", { name: "Show hidden" })).toBeNull();
});

test("a line hidden before shows no button for it on the next visit", async () => {
  hidden.add("setup_checklist:7:boundaries");
  renderApp();
  await screen.findByRole("button", { name: "Show hidden" });
  expect(screen.queryByRole("button", { name: BOUNDARIES_LINE })).toBeNull();
  // Only that line: the card has nothing else outstanding, so it is gone entirely.
  expect(screen.queryByRole("region", { name: "Setup" })).toBeNull();
});

test("hiding the last prompt removes the whole section, heading included", async () => {
  onboarding = state({
    subjects: [subject({ items: subject().items.map((i) => ({ ...i, state: "set_by_you" })) })],
  });
  todayExtra = { chapter_prompts: [PROMPT] };
  renderApp();
  expect(await screen.findByText("Coming up in your plan")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Not now: Year 11 Chemistry, Chapter 4" }));
  await waitFor(() => expect(screen.queryByText("Coming up in your plan")).toBeNull());
  expect(calls[0].path).toBe("/api/v1/me/dismissals/chapter_prompt:3:9");
  expect(await screen.findByText("1 hidden")).toBeInTheDocument();
});

test("a different chapter is a new prompt and still shows", async () => {
  hidden.add("chapter_prompt:3:9");
  todayExtra = { chapter_prompts: [{ ...PROMPT, chapter_id: 10, chapter_code: "5" }] };
  renderApp();
  expect(await screen.findByText("Coming up in your plan")).toBeInTheDocument();
});

test("a failed hide puts the line back and says so", async () => {
  failPut = true;
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: BOUNDARIES_LINE }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  expect(screen.getByRole("link", { name: "Set boundaries for Chemistry" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show hidden" })).toBeNull();
});

test("Needs you has no Not now: hiding it would leave a student's work unmarked", async () => {
  attention = [
    {
      assignment_id: 3,
      assignment_title: "Forces worksheet",
      reason: "needs_review",
      detail: null,
      submission_id: 7,
      student_name: "Aya Hassan",
    },
  ];
  todayExtra = { chapter_prompts: [PROMPT] };
  renderApp();
  const needsYou = (await screen.findByText("Needs you")).closest("section")!;
  expect(within(needsYou).queryByRole("button", { name: /Not now/ })).toBeNull();
  // The prompts above it do have one: this is the NeedsYou rule, not a missing feature.
  expect(screen.getAllByRole("button", { name: /Not now/ }).length).toBeGreaterThan(0);
});

function inFlowState() {
  // A new tutor: no class, so the no-class state is what the Overview falls to.
  todayExtra = { class_count: 0 };
  return state({
    in_flow: true,
    account: item("account_basics", "default"),
    subjects: [],
    next_step: { key: "syllabus", subject_id: null, group_id: null },
  });
}

test("skipping a step moves the guide on to the next one", async () => {
  onboarding = inFlowState();
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: "Not now: Syllabus" }));
  await waitFor(() =>
    expect(
      within(document.getElementById("onboarding-step-account")!).getByRole("button"),
    ).toHaveAttribute("aria-expanded", "true"),
  );
  expect(calls[0].path).toBe("/api/v1/me/dismissals/setup_step:syllabus");
  expect(screen.getByText("Put aside")).toBeInTheDocument();
});

test("when every remaining step is skipped the guide goes and the plain Overview shows", async () => {
  onboarding = inFlowState();
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: "Not now: Syllabus" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Not now: Time zone and weekly summary" }),
  );
  expect(await screen.findByText("No classes yet.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { level: 1, name: "Set up your first class" })).toBeNull();
  expect(await screen.findByText("2 hidden")).toBeInTheDocument();
});

test("Not now on the whole guide shows the Overview, and Show hidden brings the guide back", async () => {
  onboarding = inFlowState();
  renderApp();
  fireEvent.click(
    await screen.findByRole("button", { name: "Not now: setting up your first class" }),
  );
  expect(await screen.findByText("No classes yet.")).toBeInTheDocument();
  expect(calls[0].path).toBe("/api/v1/me/dismissals/setup_guide");

  fireEvent.click(await screen.findByRole("button", { name: "Show hidden" }));
  expect(
    await screen.findByRole("heading", { level: 1, name: "Set up your first class" }),
  ).toBeInTheDocument();
});
