import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import MistakeCategoriesPage from "../tutor/MistakeCategoriesPage";

/* The mistake-category editor (4.1, AV-39). What has to hold on screen:
   a list nobody has saved never reads as the organisation's own decision
   (PROD-8/UX-20), and the save is blocked on exactly what the API would
   reject — so a tutor is told beside the field rather than by a failed
   request. The backend's own checks live in schemas/mistake_categories.py;
   these two must not drift apart. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
];

const DEFAULTS = [
  { id: null, name: "Careless", description: "The method was right; execution slipped." },
  { id: null, name: "Content gap", description: "The method was not known." },
];

function stub(options: { source?: "organization" | "none"; categories?: unknown[] } = {}) {
  const source = options.source ?? "none";
  const categories = options.categories ?? DEFAULTS;
  const saved: unknown[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

      if (method === "GET" && path === "/api/v1/subjects") return json(SUBJECTS);
      if (/^\/api\/v1\/subjects\/\d+\/mistake-categories$/.test(path)) {
        if (method === "PUT") {
          const body = JSON.parse(String(init?.body));
          saved.push(body);
          // The API answers a save with the stored rows, ids included — a stub
          // that withheld them would hide the re-seeding the page depends on.
          return json({
            subject_id: 7,
            subject_name: "Chemistry",
            source: "organization",
            categories: body.categories.map((c: { name: string }, i: number) => ({
              id: i + 1,
              name: c.name,
              description: null,
            })),
          });
        }
        return json({
          subject_id: 7,
          subject_name: "Chemistry",
          source,
          categories,
        });
      }
      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
  return { saved };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MistakeCategoriesPage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a list nobody has saved is not presented as the organisation's own", async () => {
  // The whole point of offering defaults rather than writing them: until the
  // tutor saves, nothing is tagged against any of this, and the screen must
  // not imply otherwise (PROD-8, UX-20).
  stub({ source: "none" });
  renderPage();

  expect(await screen.findByText(/not your organisation's own/i)).toBeTruthy();
  expect(screen.queryByText(/^Your organisation's mistake categories\.$/)).toBeNull();
});

test("a saved list says it belongs to the organisation", async () => {
  stub({
    source: "organization",
    categories: [{ id: 3, name: "Rushed the last page", description: null }],
  });
  renderPage();

  expect(await screen.findByText(/Your organisation's mistake categories/i)).toBeTruthy();
  expect(screen.queryByText(/not your organisation's own/i)).toBeNull();
});

test("saving is blocked while a name is empty, and allowed once it is filled", async () => {
  // Mirrors the API's own rejection. A save that reaches the server and comes
  // back 422 tells the tutor nothing about which row was wrong.
  stub({ source: "organization", categories: [{ id: 3, name: "Careless", description: null }] });
  renderPage();

  const name = await screen.findByDisplayValue("Careless");
  const saveButton = () => screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;

  fireEvent.change(name, { target: { value: "  " } });
  await waitFor(() => expect(saveButton().disabled).toBe(true));

  fireEvent.change(name, { target: { value: "Misread the question" } });
  await waitFor(() => expect(saveButton().disabled).toBe(false));
});

test("saving is blocked while two categories share a name, ignoring case", async () => {
  // The API treats "Careless" and "careless" as one name, so the screen has to
  // as well — otherwise the tutor is allowed to submit something that cannot
  // be stored.
  stub({
    source: "organization",
    categories: [
      { id: 3, name: "Careless", description: null },
      { id: 4, name: "Content gap", description: null },
    ],
  });
  renderPage();

  const second = await screen.findByDisplayValue("Content gap");
  fireEvent.change(second, { target: { value: "careless" } });

  await waitFor(() =>
    expect((screen.getByRole("button", { name: /save/i }) as HTMLButtonElement).disabled).toBe(
      true,
    ),
  );
});

test("a saved category keeps its id, so a second save edits rather than duplicates", async () => {
  // The reply's ids are what make the next save an update. Dropping them made
  // every re-save look like a fresh list to the API.
  const { saved } = stub({ source: "none" });
  renderPage();

  await screen.findByDisplayValue("Careless");
  fireEvent.click(screen.getByRole("button", { name: /save/i }));

  await waitFor(() => expect(saved.length).toBe(1));
  // First save: the offered defaults carry no id, so they are new.
  expect((saved[0] as { categories: { id?: number }[] }).categories.every((c) => !c.id)).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => expect(saved.length).toBe(2));
  // Second save: every row now carries the id the first reply gave it.
  expect((saved[1] as { categories: { id?: number }[] }).categories.every((c) => !!c.id)).toBe(
    true,
  );
});
