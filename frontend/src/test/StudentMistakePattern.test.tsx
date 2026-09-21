import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import HomeworkPage from "../student/HomeworkPage";
import { ABSENT } from "../lib/labels";

/* The student's own mistake pattern, on their homework page (4.5).

   Three failures this section exists not to commit. A subject nobody has
   checked must never read as a clean one — `analysed_questions === 0` is
   absence and is rendered as absence, never as "0 mistakes" (PROD-2, UX-19),
   and a failed request gets a third wording rather than falling through to
   either. And severity must never reach the screen: the endpoint does not send
   it, and the test below sends it anyway, because "the server does not send
   it" stops being a control the moment a component starts reading fields off
   whatever arrives. */

const CHEMISTRY = {
  subject_id: 3,
  subject_name: "Chemistry",
  analysed_questions: 4,
  total_mistakes: 5,
  categories: [
    { category_id: 1, category_name: "Careless", mistakes: 3 },
    { category_id: 2, category_name: "Content gap", mistakes: 2 },
  ],
};

const PHYSICS = {
  subject_id: 4,
  subject_name: "Physics",
  analysed_questions: 6,
  total_mistakes: 0,
  categories: [],
};

const BIOLOGY = {
  subject_id: 5,
  subject_name: "Biology",
  analysed_questions: 0,
  total_mistakes: 0,
  categories: [],
};

/** Answers the page; `mistakes` is what `/me/mistakes` returns, or a status to
 *  fail it with. The assignment list answers empty so it stays out of the way. */
function stub(mistakes: unknown, failWith?: number) {
  // Flipped mid-test so a later refetch can fail after a first load succeeded.
  const state = { failWith };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/v1/me/mistakes") {
        if (state.failWith) {
          return new Response(JSON.stringify({ detail: "boom" }), { status: state.failWith });
        }
        return new Response(JSON.stringify(mistakes), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
  return state;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HomeworkPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => vi.unstubAllGlobals());

test("each subject's categories and counts are rendered", async () => {
  stub([CHEMISTRY, PHYSICS]);
  renderPage();

  const chemistry = (await screen.findByText("Chemistry")).closest("li")!;
  expect(
    within(chemistry).getByText("5 mistakes across 4 questions looked at"),
  ).toBeInTheDocument();
  expect(within(chemistry).getByText("Careless 3")).toBeInTheDocument();
  expect(within(chemistry).getByText("Content gap 2")).toBeInTheDocument();
});

test("a subject nobody has checked reads as absent, never as a clean record", async () => {
  stub([BIOLOGY]);
  renderPage();

  const biology = (await screen.findByText("Biology")).closest("li")!;
  expect(within(biology).getByText(new RegExp(ABSENT.noEvidence))).toBeInTheDocument();
  expect(screen.queryByText(/0 mistakes/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No mistakes noted/)).not.toBeInTheDocument();
});

test("checked with nothing found reads differently from nothing checked", async () => {
  stub([PHYSICS, BIOLOGY]);
  renderPage();

  const physics = (await screen.findByText("Physics")).closest("li")!;
  expect(
    within(physics).getByText("No mistakes noted in the 6 questions looked at so far."),
  ).toBeInTheDocument();
  // The same two zero-mistake subjects, and they must not say the same thing.
  const biology = screen.getByText("Biology").closest("li")!;
  expect(within(biology).getByText(new RegExp(ABSENT.noEvidence))).toBeInTheDocument();
  expect(within(physics).queryByText(new RegExp(ABSENT.noEvidence))).not.toBeInTheDocument();
});

// Pins that a first load which fails renders the error wording rather than a
// clean or empty record. It does NOT pin the branch order: on a first-load 500
// `data` is undefined anyway, so this passes even with the `isError` check
// removed. The refetch test below is what holds that.
test("a failed request reads as an error, not as an empty or clean record", async () => {
  stub(null, 500);
  renderPage();

  expect(await screen.findByText(new RegExp(ABSENT.loadFailed))).toBeInTheDocument();
  expect(screen.queryByText(/No mistakes noted/)).not.toBeInTheDocument();
  expect(screen.queryByText(new RegExp(ABSENT.noEvidence))).not.toBeInTheDocument();
});

test("severity never reaches the screen, even when the server sends it", async () => {
  // The tutor's shape, served at the student's URL. The endpoint does not do
  // this; the assertion is that the component could not show it if it did.
  stub([
    {
      ...CHEMISTRY,
      severity_total: 11,
      categories: [
        { category_id: 1, category_name: "Careless", mistakes: 3, severity_total: 5 },
        { category_id: 2, category_name: "Content gap", mistakes: 2, severity_total: 6 },
      ],
    },
  ]);
  renderPage();

  await screen.findByText("5 mistakes across 4 questions looked at");
  expect(screen.queryByText(/severity/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/11/)).not.toBeInTheDocument();
  // And the categories themselves render without it, rather than not rendering.
  expect(screen.getByText("Careless 3")).toBeInTheDocument();
});

test("a student with no subjects is not told about mistakes at all", async () => {
  stub([]);
  renderPage();

  await waitFor(() => expect(screen.getByText(/No homework yet/)).toBeInTheDocument());
  expect(screen.queryByText("The kinds of mistake in your work")).not.toBeInTheDocument();
});

test("a refetch that fails is reported, not papered over with the last good answer", async () => {
  // The branch order is what this holds in place. Checking `!d` before
  // `isError` leaves the previous counts on screen as though they were
  // current, which is the same PROD-2 failure in slower motion: a number shown
  // as a measurement nobody has just taken.
  const state = stub([CHEMISTRY]);
  const client = renderPage();
  await screen.findByText("5 mistakes across 4 questions looked at");

  state.failWith = 500;
  await client.invalidateQueries({ queryKey: ["my-mistakes"] });

  await waitFor(() => expect(screen.getByText(new RegExp(ABSENT.loadFailed))).toBeInTheDocument());
  expect(screen.queryByText("5 mistakes across 4 questions looked at")).not.toBeInTheDocument();
});
