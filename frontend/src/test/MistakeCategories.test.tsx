import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import MistakeCategoriesPage from "../tutor/MistakeCategoriesPage";
import { ABSENT } from "../lib/labels";

/* The mistake-category editor (4.1, AV-39). What has to hold on screen:
   a list nobody has saved never reads as the organisation's own decision
   (PROD-8/UX-20), and the save is blocked on exactly what the API would
   reject — so a tutor is told beside the field rather than by a failed
   request. The backend's own checks live in schemas/mistake_categories.py;
   these two must not drift apart. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
  { id: 9, exam_board: "Edexcel IGCSE", code: "4BI1", name: "Biology", grade_scale: "9-1" },
];

const DEFAULTS = [
  { id: null, name: "Careless", description: "The method was right; execution slipped." },
  { id: null, name: "Content gap", description: "The method was not known." },
];

function stub(
  options: {
    source?: "organization" | "none";
    categories?: unknown[];
    /** What each subject holds, when a test needs more than one. */
    bySubject?: Record<number, { source: string; categories: unknown[] }>;
    /** Make the save fail with this status and detail. */
    failSaveWith?: { status: number; detail: string };
  } = {},
) {
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
      const match = /^\/api\/v1\/subjects\/(\d+)\/mistake-categories$/.exec(path);
      if (match) {
        const subject = Number(match[1]);
        const name = SUBJECTS.find((s) => s.id === subject)!.name;
        // PUT is answered before the `bySubject` GET table is consulted —
        // otherwise a stub that describes two subjects can never model a save
        // at all, because every request to those paths is read as a read.
        if (method === "PUT" && options.failSaveWith) {
          return new Response(JSON.stringify({ detail: options.failSaveWith.detail }), {
            status: options.failSaveWith.status,
          });
        }
        if (method === "PUT") {
          const body = JSON.parse(String(init?.body));
          saved.push(body);
          // The API answers a save with the stored rows, ids included — a stub
          // that withheld them would hide the re-seeding the page depends on.
          // It echoes the subject from the URL rather than naming one: a reply
          // claiming a subject the caller did not ask about is written into
          // that subject's cache entry and skips its next hydration, so a stub
          // that hardcoded it would quietly plant that bug in any future test
          // that saves on a second subject.
          return json({
            subject_id: subject,
            subject_name: name,
            source: "organization",
            categories: body.categories.map(
              (c: { id?: number; name: string; description?: string }, i: number) => ({
                id: c.id ?? i + 1,
                name: c.name,
                description: c.description ?? null,
              }),
            ),
          });
        }
        if (options.bySubject) {
          const held = options.bySubject[subject];
          return json({
            subject_id: subject,
            subject_name: name,
            source: held.source,
            categories: held.categories,
          });
        }
        return json({ subject_id: subject, subject_name: name, source, categories });
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
  const rendered = render(
    <QueryClientProvider client={client}>
      <MistakeCategoriesPage />
    </QueryClientProvider>,
  );
  return { ...rendered, client };
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

test("new server data arriving mid-edit does not overwrite what the tutor has typed", async () => {
  // These categories belong to the organisation, not to one tutor, so a
  // colleague saving the same subject in another tab is the ordinary way the
  // server's answer changes while someone is editing — and a window regaining
  // focus is enough to fetch it. Re-seeding the draft on every query update
  // silently replaced the unsaved edit: no warning, no diff, no sign anyone
  // else had touched it.
  //
  // Written against the cache rather than by forcing a refetch, because that
  // is the state a refetch produces and it produces it deterministically.
  stub({ source: "organization", categories: [{ id: 3, name: "Careless", description: null }] });
  const { client } = renderPage();

  const name = await screen.findByDisplayValue("Careless");
  fireEvent.change(name, { target: { value: "Half-typed edit" } });

  client.setQueryData(["mistake-categories", 7], {
    subject_id: 7,
    subject_name: "Chemistry",
    source: "organization",
    categories: [{ id: 3, name: "Saved by a colleague", description: null }],
  });

  await waitFor(() => expect(screen.getByDisplayValue("Half-typed edit")).toBeTruthy());
  expect(screen.queryByDisplayValue("Saved by a colleague")).toBeNull();
});

test("switching subject shows that subject's categories, never the previous one's", async () => {
  // Switching back to a subject already in the cache renders its data
  // synchronously, while the draft still holds the previous subject's rows.
  // Saving in that window wrote one subject's list onto another — and because
  // rows offered as defaults carry no id, the API matched them by name and
  // took them as edits rather than refusing them.
  stub({
    bySubject: {
      7: {
        source: "organization",
        categories: [{ id: 1, name: "Chemistry only", description: null }],
      },
      9: {
        source: "organization",
        categories: [{ id: 2, name: "Biology only", description: null }],
      },
    },
  });
  renderPage();

  await screen.findByDisplayValue("Chemistry only");

  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "9" } });
  expect(await screen.findByDisplayValue("Biology only")).toBeTruthy();
  expect(screen.queryByDisplayValue("Chemistry only")).toBeNull();

  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "7" } });
  expect(await screen.findByDisplayValue("Chemistry only")).toBeTruthy();
  expect(screen.queryByDisplayValue("Biology only")).toBeNull();
});

test("removing a row moves focus somewhere deliberate", async () => {
  // The button the tutor pressed stops existing. A browser then drops focus to
  // <body>, which puts a keyboard or screen-reader user back at the top of the
  // document with no way to tell what happened.
  stub({
    source: "organization",
    categories: [
      { id: 3, name: "Careless", description: null },
      { id: 4, name: "Content gap", description: null },
    ],
  });
  renderPage();

  await screen.findByDisplayValue("Careless");
  fireEvent.click(screen.getByRole("button", { name: /Remove Careless/i }));

  expect(document.activeElement).toBe(screen.getByRole("button", { name: /Add a category/i }));
});

test("a rejected save shows the server's reason, not generic advice", async () => {
  // "Refresh the page to try again" is wrong advice for a rejected save, and
  // it is wrong exactly when the real message matters most.
  stub({
    source: "organization",
    categories: [{ id: 3, name: "Careless", description: null }],
    failSaveWith: { status: 404, detail: "Mistake category not found" },
  });
  renderPage();

  await screen.findByDisplayValue("Careless");
  fireEvent.click(screen.getByRole("button", { name: /save/i }));

  expect(await screen.findByText(/Mistake category not found/)).toBeTruthy();
});

test("subjects that fail to load say so, rather than reading as none existing", async () => {
  // A transient failure rendered as "No subjects yet." sends a tutor who has
  // subjects off to add a syllabus they already have, and hides that anything
  // went wrong at all (PROD-2, UX-19).
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ detail: "upstream is down" }), { status: 500 }),
    ),
  );
  renderPage();

  expect(await screen.findByText(ABSENT.loadFailed)).toBeTruthy();
  expect(screen.queryByText(/No subjects yet/i)).toBeNull();
});

test("a name the API would reject is marked on the row it is wrong on", async () => {
  // Save going grey says something is wrong somewhere. With forty categories
  // on screen, a page footnote does not say which — and a screen reader
  // reaching the disabled button has nothing tying it to a field.
  stub({
    source: "organization",
    categories: [
      { id: 3, name: "Careless", description: null },
      { id: 4, name: "Content gap", description: null },
    ],
  });
  renderPage();

  const second = await screen.findByDisplayValue("Content gap");
  fireEvent.change(second, { target: { value: "  " } });

  await waitFor(() => expect(second.getAttribute("aria-invalid")).toBe("true"));
  const describedBy = second.getAttribute("aria-describedby")!;
  expect(document.getElementById(describedBy)?.textContent).toMatch(/needs a name/i);
  // And the row that is not the problem is not marked as one.
  expect(screen.getByDisplayValue("Careless").getAttribute("aria-invalid")).toBe("false");
});
