import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ImprovementPage from "../student/ImprovementPage";
import type { SubjectImprovement } from "../api/improvement";

/* The Improvement tab. The rule these tests exist to hold: nothing on this page
   belongs to anyone else. No classmate row, no classmate delta, no "← you"
   marker in a list of other people, no names, no initials, no avatars. */

function view(over: Partial<SubjectImprovement> = {}): SubjectImprovement {
  return {
    subject_id: 1,
    subject_name: "Chemistry",
    window_days: 30,
    member_count: 11,
    periods: [
      { label: "This month", delta: 6, rank: 3, ranked_count: 11, banded: false },
      { label: "Last month", delta: 2, rank: 7, ranked_count: 11, banded: true },
    ],
    focus: [{ topic_code: "3.2", topic_title: "Rates", score: 41 }],
    ...over,
  };
}

function stubFetch(views: SubjectImprovement[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(views), { status: 200 })),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ImprovementPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a top-half placing is exact", async () => {
  stubFetch([view()]);
  renderPage();
  expect(await screen.findByText("You're 3rd of 11 this month.")).toBeInTheDocument();
});

test("a bottom-half placing is banded, never a bare number", async () => {
  // "9th of 11" discourages even with nobody named — the exact failure the
  // student surfaces are designed against.
  stubFetch([
    view({
      periods: [{ label: "This month", delta: -2, rank: 9, ranked_count: 11, banded: true }],
    }),
  ]);
  const { container } = renderPage();
  expect(
    await screen.findByText("You're in the second half of your class this month."),
  ).toBeInTheDocument();
  expect(container.textContent).not.toContain("9th");
});

test("a gate not met states the absence and still shows the reader's own movement", async () => {
  stubFetch([
    view({
      periods: [{ label: "This month", delta: 5, rank: null, ranked_count: 4, banded: false }],
      member_count: 4,
    }),
  ]);
  const { container } = renderPage();
  expect(await screen.findByText(/Not enough of your class/)).toBeInTheDocument();
  // Their own delta is theirs and needs no class to be true.
  expect(container.textContent).toContain("▲ +5");
});

test("no classmate appears anywhere on the page", async () => {
  stubFetch([view()]);
  const { container } = renderPage();
  await screen.findByText("You're 3rd of 11 this month.");
  expect(screen.queryByText(/← you/)).not.toBeInTheDocument();
  expect(container.querySelectorAll("img")).toHaveLength(0);
  // A roster would show as repeated rows of names; there are none to show.
  expect(container.textContent).not.toMatch(/Student \d/);
});

test("a reader with no delta gets words, not a zero", async () => {
  stubFetch([
    view({
      periods: [{ label: "This month", delta: null, rank: null, ranked_count: 0, banded: false }],
    }),
  ]);
  const { container } = renderPage();
  expect(await screen.findByText("not enough data yet")).toBeInTheDocument();
  expect(container.textContent).not.toContain("▲ +0");
});

test("what would move you up is the reader's own weakest topics", async () => {
  stubFetch([view()]);
  renderPage();
  expect(await screen.findByText("3.2 Rates")).toBeInTheDocument();
  expect(screen.getByText("41%")).toBeInTheDocument();
});

test("a focus topic with no confident evidence says so rather than showing a score", async () => {
  stubFetch([view({ focus: [{ topic_code: "4.1", topic_title: "Electrolysis", score: null }] })]);
  renderPage();
  expect(await screen.findByText("4.1 Electrolysis")).toBeInTheDocument();
  expect(screen.getByText("not enough data yet")).toBeInTheDocument();
});

test("nothing to compare yet is a stated absence, not an empty board", async () => {
  stubFetch([]);
  renderPage();
  expect(await screen.findByText("Nothing to compare yet.")).toBeInTheDocument();
});
