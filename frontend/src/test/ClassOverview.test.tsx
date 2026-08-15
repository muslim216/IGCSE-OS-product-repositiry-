import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ClassOverviewPanel from "../tutor/ClassOverview";
import type { ClassOverview } from "../api/today";

function learner(over: Partial<ClassOverview["learners"][number]> = {}) {
  return {
    student_id: 1,
    student_name: "Sara",
    score: 62,
    predicted_grade: "6",
    status: "needs_attention" as const,
    direction: "down" as const,
    ...over,
  };
}

const BASE: ClassOverview = {
  group_id: 5,
  name: "Chem",
  subject_name: "Chemistry",
  score: 62,
  predicted_grade: "6",
  status: "needs_attention",
  boundaries_missing: false,
  member_count: 11,
  students_with_evidence: 9,
  needs_you: [],
  learners: [],
  weak_topics: [],
};

function stubFetch(overview: ClassOverview, narrative: string | null = null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/narrative")) {
        return json({ text: narrative, generated_at: null, prompt_version: null });
      }
      if (url.includes("/today/classes/")) return json(overview);
      return json([]);
    }),
  );
}

function renderPanel() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ClassOverviewPanel groupId={5} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a declining learner appears in NEEDS YOU", async () => {
  const slider = learner({ student_name: "Slider", direction: "down", predicted_grade: "6" });
  stubFetch({ ...BASE, needs_you: [slider], learners: [slider] });
  renderPanel();

  const section = (await screen.findByText("Needs you")).closest("section")!;
  expect(within(section).getByText("Slider")).toBeInTheDocument();
});

test("a stable low learner is absent from NEEDS YOU but present under Learners", async () => {
  const steady = learner({
    student_id: 2,
    student_name: "Steady",
    direction: "flat",
    predicted_grade: "4",
    status: "at_risk",
  });
  stubFetch({ ...BASE, needs_you: [], learners: [steady] });
  renderPanel();

  const learners = (await screen.findByText("Learners")).closest("section")!;
  expect(within(learners).getByText("Steady")).toBeInTheDocument();
  // The section that would single them out is not rendered at all.
  expect(screen.queryByText("Needs you")).not.toBeInTheDocument();
});

test("a learner with one readiness point renders no arrow", async () => {
  const fresh = learner({ student_name: "New", direction: null });
  stubFetch({ ...BASE, learners: [fresh] });
  renderPanel();

  await screen.findByText("New");
  // "→" would be a claim the data does not support.
  expect(screen.queryByText("→")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/Trending/)).not.toBeInTheDocument();
});

test("a class with nobody in it renders the empty room, not a dashboard of absences", async () => {
  stubFetch({
    ...BASE,
    member_count: 0,
    students_with_evidence: 0,
    score: null,
    predicted_grade: null,
    status: null,
  });
  renderPanel();

  expect(await screen.findByText(/No one has joined yet/)).toBeInTheDocument();
  expect(screen.queryByText("Learners")).not.toBeInTheDocument();
  expect(screen.queryByText("Why")).not.toBeInTheDocument();
  // The state changes between visits, and the one thing the tutor can do to
  // change it is share the code again — so that is the only control here.
  expect(screen.getByRole("button", { name: /Share again/ })).toBeInTheDocument();
  expect(await screen.findByText(/Readiness appears once you've marked/)).toBeInTheDocument();
});

test("the parent narrative is read-only with a regenerate, and no review state", async () => {
  stubFetch({ ...BASE, learners: [learner()] }, "Sara is finding bonding hard.");
  renderPanel();

  expect(await screen.findByText("Sara is finding bonding hard.")).toBeInTheDocument();
  // D2: the only control is a correction, never an approval.
  expect(screen.getByRole("button", { name: "Prepare again" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /suppress/i })).not.toBeInTheDocument();
});

test("a subject with no boundaries offers the action that fixes it", async () => {
  stubFetch({ ...BASE, status: null, predicted_grade: null, boundaries_missing: true });
  renderPanel();
  expect(await screen.findByText("no grade boundaries set")).toBeInTheDocument();
  expect(screen.getByText("Set them →")).toBeInTheDocument();
});
