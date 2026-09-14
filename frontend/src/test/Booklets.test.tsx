import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import BookletsPage from "../tutor/BookletsPage";

const booklet = {
  id: 1,
  subject_id: 1,
  title: null,
  display_title: "Chemistry 0620 · November 2024 booklet",
  status: "review",
  file_name: "booklet.pdf",
  mark_scheme_name: null,
  error: null,
  paper_count: 0,
  created_at: "2026-01-01T00:00:00Z",
};

const draft = {
  papers: [
    {
      title: "Multiple Choice",
      session_label: "November 2024",
      paper_number: "Paper 1",
      first_page: 1,
      last_page: 16,
    },
    {
      title: "Theory",
      session_label: "November 2024",
      paper_number: "Paper 4",
      first_page: 17,
      last_page: 40,
    },
  ],
  scheme_papers: null,
  scheme_mismatch: null,
};

interface Call {
  url: string;
  method: string;
  body: string | null;
}

/** Every request the page makes, so a test can assert what the tutor's click
 *  actually sent rather than that some handler ran. */
function mockFetch(list: unknown[], detail: unknown = null): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : null,
      });
      // /booklets/1, /booklets/1/draft, /booklets/1/retry, /booklets/1/approve
      // all answer with a BookletDetail, which is what the API does too.
      if (/\/booklets\/\d+/.test(url)) {
        return new Response(JSON.stringify(detail ?? booklet), { status: 200 });
      }
      if (url.includes("/booklets")) {
        return new Response(JSON.stringify(list), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
  return calls;
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <BookletsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Open the review table for the one booklet on screen. */
async function openReview() {
  fireEvent.click(await screen.findByRole("button", { name: "Check the papers" }));
  return screen.findByRole("table");
}

beforeEach(() => {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
});

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

test("a booklet still being read says so rather than showing an empty table", async () => {
  mockFetch([{ ...booklet, status: "extracting" }]);
  renderPage();
  expect(await screen.findByText(/Reading the list of papers out of this booklet/)).toBeVisible();
  // No table, and above all no "0 papers" — nothing has been counted yet
  // (`PROD-2`, `UX-19`).
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByText(/0 papers/)).not.toBeInTheDocument();
});

test("a booklet the AI could not read shows why, and offers to try again", async () => {
  const calls = mockFetch([
    { ...booklet, status: "extraction_failed", error: "The file was not a readable PDF" },
  ]);
  renderPage();
  expect(
    await screen.findByText(/Couldn't read this booklet: The file was not a readable PDF/),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(calls.some((c) => c.url.endsWith("/booklets/1/retry") && c.method === "POST")).toBe(
      true,
    ),
  );
});

test("the review table shows the papers the AI found", async () => {
  mockFetch([booklet], { ...booklet, draft });
  renderPage();
  await openReview();
  expect(screen.getByLabelText("Title, paper 1")).toHaveValue("Multiple Choice");
  expect(screen.getByLabelText("Paper number, paper 2")).toHaveValue("Paper 4");
  expect(screen.getByLabelText("First page, paper 2")).toHaveValue(17);
  expect(screen.getByLabelText("Last page, paper 2")).toHaveValue(40);
});

test("a mark scheme that disagrees with the paper list is put in front of the tutor", async () => {
  mockFetch([booklet], {
    ...booklet,
    draft: { ...draft, scheme_mismatch: "The mark scheme lists 3 papers; the booklet has 2." },
  });
  renderPage();
  await openReview();
  const warning = screen.getByRole("alert");
  expect(warning).toHaveTextContent("The mark scheme lists 3 papers; the booklet has 2.");
  // The tutor has the final word, and the page says so rather than blocking
  // approval (`PROD-7`).
  expect(warning).toHaveTextContent(/You decide which is right/);
});

test("no warning is invented when the mark scheme agreed", async () => {
  mockFetch([booklet], { ...booklet, draft });
  renderPage();
  await openReview();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("correcting a row and saving sends the whole draft back", async () => {
  const calls = mockFetch([booklet], { ...booklet, draft });
  renderPage();
  await openReview();

  fireEvent.change(screen.getByLabelText("Title, paper 1"), {
    target: { value: "Multiple Choice (Core)" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  const put = await waitFor(() => {
    const call = calls.find((c) => c.method === "PUT" && c.url.endsWith("/booklets/1/draft"));
    expect(call).toBeDefined();
    return call!;
  });
  const sent = JSON.parse(put.body!);
  expect(sent.papers).toHaveLength(2);
  expect(sent.papers[0].title).toBe("Multiple Choice (Core)");
  // Untouched fields still ride along — the edit must not drop the AI's
  // reading of the mark scheme.
  expect(sent.papers[1].last_page).toBe(40);
  expect(sent).toHaveProperty("scheme_papers");
  expect(sent).toHaveProperty("scheme_mismatch");
});

test("a row can be added and one dropped before the tutor saves", async () => {
  const calls = mockFetch([booklet], { ...booklet, draft });
  renderPage();
  await openReview();

  fireEvent.click(screen.getByRole("button", { name: "Remove paper 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Add a paper" }));
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  const put = await waitFor(() => {
    const call = calls.find((c) => c.method === "PUT");
    expect(call).toBeDefined();
    return call!;
  });
  const sent = JSON.parse(put.body!);
  expect(sent.papers).toHaveLength(2);
  expect(sent.papers[0].title).toBe("Theory");
  expect(sent.papers[1].title).toBe("");
});

test("approving asks the server to cut the papers", async () => {
  const calls = mockFetch([booklet], { ...booklet, draft });
  renderPage();
  await openReview();

  fireEvent.click(screen.getByRole("button", { name: /Approve and cut the papers/ }));
  await waitFor(() =>
    expect(calls.some((c) => c.url.endsWith("/booklets/1/approve") && c.method === "POST")).toBe(
      true,
    ),
  );
});
