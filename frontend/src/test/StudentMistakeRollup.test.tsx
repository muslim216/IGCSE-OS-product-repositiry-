import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";
import { ABSENT } from "../lib/labels";

/* The mistake rollup on the tutor's student profile (4.4).

   What has to hold on screen: a student nobody has examined never reads as a
   clean one (PROD-2, UX-19 — that is the whole reason this phase exists), a
   failed request never reads as either, and the named `topicless` /
   `chapterless` buckets are shown rather than quietly dropped, because
   dropping them is what stops the per-topic rows reconciling with the
   readiness factor's subject count (RISK-5). */

const SUBJECT = {
  subject_id: 3,
  subject_name: "Chemistry",
  exam_board: "Edexcel IGCSE",
  grade_scale: "9-1",
  score: null,
  predicted_grade: null,
  status: null,
  averaging_score: null,
  averaging_grade: null,
  marked_piece_count: 0,
  direction: null,
  month_delta: null,
  topics_with_evidence: 0,
  topic_count: 0,
  topics: [],
  weak_topics: [],
  engine: "v2",
  is_updating: false,
  computed_at: null,
  rationale: null,
  recommended_revision: null,
};

const tally = (
  mistakes: number,
  severity_total: number,
  categories: {
    category_id: number;
    category_name: string;
    mistakes: number;
    severity_total: number;
  }[] = [],
) => ({ mistakes, severity_total, categories });

const CARELESS = { category_id: 1, category_name: "Careless", mistakes: 3, severity_total: 5 };
const GAP = { category_id: 2, category_name: "Content gap", mistakes: 1, severity_total: 4 };

const POPULATED = {
  student_id: 2,
  subject_id: 3,
  analysed_questions: 8,
  total: tally(5, 11, [CARELESS, GAP]),
  topics: [
    {
      topic_id: 10,
      topic_title: "Photosynthesis",
      chapter_id: 100,
      tally: tally(4, 9, [CARELESS]),
    },
    { topic_id: 11, topic_title: "Respiration", chapter_id: 100, tally: tally(3, 6, [GAP]) },
  ],
  topicless: tally(1, 2, [CARELESS]),
  chapters: [{ chapter_id: 100, chapter_title: "Plant biology", tally: tally(5, 10, [CARELESS]) }],
  chapterless: tally(2, 3, [GAP]),
};

/** Answers the whole page; `mistakes` is what the rollup endpoint returns, or
 *  a status to fail it with. Every other path answers empty so the rest of the
 *  profile renders without standing in the way. */
function stub(mistakes: unknown, failWith?: number, subjects = [SUBJECT]) {
  const calls: string[] = [];
  // Flipped mid-test so a later refetch can fail after a first load succeeded.
  const state = { failWith };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      calls.push(url.pathname + url.search);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.pathname === "/api/v1/readiness/students/2") {
        return json({ student_id: 2, student_name: "Sara", subjects });
      }
      if (url.pathname === "/api/v1/students/2/mistakes") {
        if (state.failWith) {
          return new Response(JSON.stringify({ detail: "boom" }), { status: state.failWith });
        }
        // Keyed by the subject asked for, so a test with several subjects
        // gets a distinct body per section rather than one shared answer.
        const asked = Number(url.searchParams.get("subject_id"));
        return json(
          typeof mistakes === "object" && mistakes !== null && "bySubject" in mistakes
            ? (mistakes as { bySubject: Record<number, unknown> }).bySubject[asked]
            : mistakes,
        );
      }
      return json([]);
    }),
  );
  return { calls, state };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/students/2"]}>
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => vi.unstubAllGlobals());

test("topics and chapters render with their counts and category breakdowns", async () => {
  const { calls } = stub(POPULATED);
  renderPage();

  // The subject comes from the page's own derivation (the student's first
  // subject), not a second selector of this section's own.
  await waitFor(() => expect(calls).toContain("/api/v1/students/2/mistakes?subject_id=3"));

  // `total` is the only subject figure: 5, not the 7 the two topic rows add to.
  expect(await screen.findByText("5 mistakes across 8 examined questions")).toBeInTheDocument();

  const photosynthesis = screen.getByText("Photosynthesis").closest("li")!;
  expect(photosynthesis).toHaveTextContent("4 mistakes");
  expect(photosynthesis).toHaveTextContent("Careless 3 · severity 5");
  const respiration = screen.getByText("Respiration").closest("li")!;
  expect(respiration).toHaveTextContent("3 mistakes");
  expect(respiration).toHaveTextContent("Content gap 1 · severity 4");

  const chapter = screen.getByText("Plant biology").closest("li")!;
  expect(chapter).toHaveTextContent("5 mistakes");
  expect(chapter).toHaveTextContent("Careless 3 · severity 5");

  // And the per-topic rows say so themselves, so nobody adds them up.
  expect(screen.getByText(/do not add up to 5/)).toBeInTheDocument();
});

test("no examined work reads as absent, not as a clean record", async () => {
  stub({
    ...POPULATED,
    analysed_questions: 0,
    total: tally(0, 0),
    topics: [],
    topicless: tally(0, 0),
    chapters: [],
    chapterless: tally(0, 0),
  });
  renderPage();

  expect(await screen.findByText(new RegExp(ABSENT.noEvidence))).toBeInTheDocument();
  // Nothing anywhere may present this student as having a record at all.
  expect(screen.queryByText(/0 mistakes/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No mistakes recorded/)).not.toBeInTheDocument();
  expect(screen.queryByText("By topic")).not.toBeInTheDocument();
});

test("examined work with no mistakes reads as a clean record", async () => {
  stub({
    ...POPULATED,
    analysed_questions: 12,
    total: tally(0, 0),
    topics: [],
    topicless: tally(0, 0),
    chapters: [],
    chapterless: tally(0, 0),
  });
  renderPage();

  expect(
    await screen.findByText("No mistakes recorded in the 12 questions examined so far."),
  ).toBeInTheDocument();
  // Visibly a different answer from the case above, not the same sentence.
  expect(screen.queryByText(new RegExp(ABSENT.noEvidence))).not.toBeInTheDocument();
});

test("the topicless and chapterless buckets are rendered and labelled", async () => {
  stub(POPULATED);
  renderPage();

  // Exact text, not `toHaveTextContent`: that is a substring match, so
  // "1 mistake" also passes against "11 mistakes" and the count half of this
  // test would hold while the number on screen was wrong.
  const topicless = (await screen.findByText("Not linked to any topic")).closest("li")!;
  expect(within(topicless).getByText("1 mistake")).toBeInTheDocument();
  expect(within(topicless).getByText("Careless 3 · severity 5")).toBeInTheDocument();

  const chapterless = screen.getByText("Topics with no chapter").closest("li")!;
  expect(within(chapterless).getByText("2 mistakes")).toBeInTheDocument();
  expect(within(chapterless).getByText("Content gap 1 · severity 4")).toBeInTheDocument();
});

test("a failed request reads as an error, not as an empty or clean record", async () => {
  stub(null, 500);
  renderPage();

  expect(await screen.findByText(new RegExp(ABSENT.loadFailed))).toBeInTheDocument();
  expect(screen.queryByText(/No mistakes recorded/)).not.toBeInTheDocument();
  expect(screen.queryByText(new RegExp(ABSENT.noEvidence))).not.toBeInTheDocument();
  expect(screen.queryByText("By topic")).not.toBeInTheDocument();
});

test("a refetch that fails is reported, not papered over with the last good answer", async () => {
  // The branch order is what this test holds in place. Checking `!d` before
  // `isError` would leave the table from the first load on screen as though it
  // were current, which is the same PROD-2 failure in slower motion: a number
  // presented as a measurement nobody has just taken.
  const { state } = stub(POPULATED);
  const client = renderPage();
  await screen.findByText("5 mistakes across 8 examined questions");

  state.failWith = 500;
  await client.invalidateQueries({ queryKey: ["student-mistakes"] });

  await waitFor(() => expect(screen.getByText(new RegExp(ABSENT.loadFailed))).toBeInTheDocument());
  expect(screen.queryByText("5 mistakes across 8 examined questions")).not.toBeInTheDocument();
  expect(screen.queryByText("By topic")).not.toBeInTheDocument();
});

test("every subject the student takes gets its own named section", async () => {
  // A single section fed by the page's derived `subjectId` rendered the first
  // subject's mistakes under a bare "Mistakes" heading and silently dropped
  // every other subject — the tutor had no way to tell a subject was missing,
  // or which one they were reading (cubic, PROD-2 at the scale of a subject).
  const PHYSICS = { ...SUBJECT, subject_id: 4, subject_name: "Physics" };
  stub(
    {
      bySubject: {
        3: POPULATED,
        4: { ...POPULATED, subject_id: 4, analysed_questions: 0, total: tally(0, 0, []) },
      },
    },
    undefined,
    [SUBJECT, PHYSICS],
  );
  renderPage();

  // Named, so the numbers cannot be read against the wrong subject.
  expect(await screen.findByText("Mistakes in Chemistry")).toBeInTheDocument();
  expect(await screen.findByText("Mistakes in Physics")).toBeInTheDocument();

  // And each section shows its own subject's answer, not the first one's.
  const physics = (await screen.findByText("Mistakes in Physics")).closest("section")!;
  expect(within(physics).getByText(new RegExp(ABSENT.noEvidence))).toBeInTheDocument();
  const chemistry = (await screen.findByText("Mistakes in Chemistry")).closest("section")!;
  expect(within(chemistry).getByText("5 mistakes across 8 examined questions")).toBeInTheDocument();
});
