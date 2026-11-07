import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SyllabusUploadPage from "../tutor/SyllabusUploadPage";

/* The review screen edits two levels since task 2.3 (AV-9): chapters, and the
   topics inside them. A draft edit that dropped the chapter it belongs to would
   still round-trip through a stub that echoes whatever it is sent, so these
   tests assert on the PUT body the page actually sends. */

const DRAFT = {
  exam_board: "Edexcel IGCSE",
  code: "4CH1",
  name: "Chemistry",
  level: null,
  grade_scale: "9-1",
  chapters: [
    {
      code: "1",
      title: "Principles of chemistry",
      topics: [
        { code: "1.1", title: "States of matter", weight: 1, children: [] },
        {
          code: "1.2",
          title: "Atoms",
          weight: 1,
          children: [{ code: "1.2.1", title: "Isotopes", weight: 1, children: [] }],
        },
      ],
    },
    {
      code: "2",
      title: "Inorganic chemistry",
      topics: [{ code: "2.1", title: "Acids and bases", weight: 1, children: [] }],
    },
  ],
};

function stub(status = "review", draft: typeof DRAFT | null = DRAFT, error: string | null = null) {
  const puts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      // The API flips a failed upload to `review` once the tutor edits the
      // draft, exactly as `edit_draft` does.
      const upload = { id: 1, title: "Chemistry 4CH1", file_name: "s.pdf", status };
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

      if (method === "GET" && path === "/api/v1/syllabus-uploads")
        return json([{ ...upload, error: null, subject_id: null, created_at: "2026-06-01" }]);
      if (method === "GET" && path === "/api/v1/syllabus-uploads/1")
        return json({
          ...upload,
          error,
          subject_id: null,
          created_at: "2026-06-01",
          draft,
        });
      if (method === "PUT" && path === "/api/v1/syllabus-uploads/1/draft") {
        const sent = JSON.parse(String(init?.body));
        puts.push(sent);
        return json({
          ...upload,
          // edit_draft flips a failed extraction to `review` on save.
          status: "review",
          error: null,
          subject_id: null,
          created_at: "2026-06-01",
          draft: sent,
        });
      }
      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
  return puts;
}

async function openDraft(expectSummary = "2 chapters, 4 topics") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SyllabusUploadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));
  await screen.findByText(expectSummary);
}

afterEach(() => vi.unstubAllGlobals());

test("the draft renders as chapters holding their own topics", async () => {
  stub();
  await openDraft();
  fireEvent.click(screen.getByRole("button", { name: "Open all" }));

  expect(screen.getByDisplayValue("Principles of chemistry")).toBeTruthy();
  expect(screen.getByDisplayValue("Inorganic chemistry")).toBeTruthy();
  // Sub-topics stay under their parent topic, inside the parent's chapter.
  expect(screen.getByDisplayValue("Isotopes")).toBeTruthy();
});

test("editing a topic keeps it in its chapter", async () => {
  const puts = stub();
  await openDraft();
  fireEvent.click(screen.getByRole("button", { name: /Show topics in Inorganic chemistry/ }));

  fireEvent.change(screen.getByDisplayValue("Acids and bases"), {
    target: { value: "Acids, bases and salts" },
  });

  await waitFor(() => expect(puts).toHaveLength(1));
  const sent = puts[0] as typeof DRAFT;
  expect(sent.chapters[1].topics[0].title).toBe("Acids, bases and salts");
  expect(sent.chapters[0].topics[0].title).toBe("States of matter");
});

test("a level the document never stated is the tutor's to set", async () => {
  const puts = stub();
  await openDraft();

  // Nothing is guessed for them (AV-7, PROD-2) — the select sits on "no level".
  const select = screen.getByLabelText("Level") as HTMLSelectElement;
  expect(select.value).toBe("");

  fireEvent.change(select, { target: { value: "a_level" } });
  await waitFor(() => expect(puts).toHaveLength(1));
  expect((puts[0] as typeof DRAFT).level).toBe("a_level");
});

test("a second edit does not drop the first", async () => {
  const puts = stub();
  await openDraft();

  // Two fields edited back to back. Each PUT sends the whole draft, so if it is
  // built from data that has not caught up, the second silently reverts the
  // first (CodeRabbit).
  fireEvent.click(screen.getByRole("button", { name: /Show topics in Principles of chemistry/ }));
  fireEvent.change(screen.getByDisplayValue("Principles of chemistry"), {
    target: { value: "Principles" },
  });
  fireEvent.change(screen.getByDisplayValue("States of matter"), {
    target: { value: "States" },
  });

  await waitFor(() => expect(puts).toHaveLength(2));
  const sent = puts[1] as typeof DRAFT;
  expect(sent.chapters[0].title).toBe("Principles");
  expect(sent.chapters[0].topics[0].title).toBe("States");
});

test("editing a failed extraction clears the retry button", async () => {
  // A cache still reading `extraction_failed` after the edit succeeded leaves
  // the retry ("Try again") on screen — one click from re-running the AI over
  // the tutor's own corrections (cubic).
  const puts = stub("extraction_failed");
  await openDraft();
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();

  fireEvent.change(screen.getByDisplayValue("Principles of chemistry"), {
    target: { value: "Principles" },
  });

  await waitFor(() => expect(puts).toHaveLength(1));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Try again" })).toBeNull());
  // The tutor's edit is still on screen, not replaced by the server echo.
  expect(screen.getByDisplayValue("Principles")).toBeTruthy();
});

test("a failed extraction with no draft offers no Apply", async () => {
  // The API refuses to apply nothing ("No syllabus draft to apply yet"), so
  // the button would only ever produce that error.
  stub("extraction_failed", null);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SyllabusUploadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));

  expect(await screen.findByText("We couldn't read this syllabus.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
});

test("a failed extraction that still has a draft can be applied", async () => {
  stub("extraction_failed");
  await openDraft();
  expect(screen.getByRole("button", { name: /Apply/ })).toBeInTheDocument();
});

async function openFailed(error: string | null) {
  stub("extraction_failed", null, error);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SyllabusUploadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));
  await screen.findByText("We couldn't read this syllabus.");
}

/* A read refused by a daily AI limit (services/ai.py) is not the document's
   fault: telling the tutor to upload a clearer copy would send them round in
   circles until the limit frees up. */
test.each([
  "This workspace has reached today's limit for AI work. It frees up within 24 hours.",
  "Avora has reached today's limit for this AI work. It frees up within 24 hours.",
])("a read stopped by a daily AI limit says so instead of blaming the file: %s", async (limit) => {
  await openFailed(limit);
  expect(screen.getByText(limit)).toBeVisible();
  expect(screen.queryByText(/upload a clearer copy/)).not.toBeInTheDocument();
});

test("any other failed read still suggests a clearer copy", async () => {
  await openFailed("The AI's answer was cut off at the output limit (128000 tokens)");
  expect(screen.getByText(/upload a clearer copy/)).toBeInTheDocument();
});

test("a read in progress says it can take a while and the tutor can leave", async () => {
  stub("extracting", null);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SyllabusUploadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));
  const status = await screen.findByText(/reading the syllabus/);
  expect(status.textContent).toMatch(/up to 45 minutes/);
  expect(status.textContent).toMatch(/leave this page/);
});

/* T-032: the review opens as a summary and the tutor asks for detail. */

test("chapters start folded, each with its counts", async () => {
  stub();
  await openDraft();

  expect(screen.getByText("2 topics · 1 sub-point")).toBeInTheDocument();
  expect(screen.getByText("1 topic")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Principles of chemistry")).toBeInTheDocument();
  expect(screen.queryByDisplayValue("States of matter")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("Acids and bases")).not.toBeInTheDocument();
});

test("opening a chapter shows topics, and a topic's toggle shows its sub-points", async () => {
  stub();
  await openDraft();

  fireEvent.click(screen.getByRole("button", { name: /Show topics in Principles of chemistry/ }));
  expect(screen.getByDisplayValue("States of matter")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Atoms")).toBeInTheDocument();
  expect(screen.queryByDisplayValue("Isotopes")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("Acids and bases")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Show sub-points of Atoms/ }));
  expect(screen.getByDisplayValue("Isotopes")).toBeInTheDocument();
});

test("Open all shows everything and Fold all hides it again", async () => {
  stub();
  await openDraft();

  fireEvent.click(screen.getByRole("button", { name: "Open all" }));
  for (const t of ["States of matter", "Atoms", "Isotopes", "Acids and bases"])
    expect(screen.getByDisplayValue(t)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Fold all" }));
  for (const t of ["States of matter", "Atoms", "Isotopes", "Acids and bases"])
    expect(screen.queryByDisplayValue(t)).not.toBeInTheDocument();
});

test("weights are hidden, a weight other than 1 shows a badge, and Show weights reveals inputs", async () => {
  const heavy = structuredClone(DRAFT);
  heavy.chapters[1].topics[0].weight = 2;
  stub("review", heavy);
  await openDraft();

  fireEvent.click(screen.getByRole("button", { name: /Show topics in Inorganic chemistry/ }));
  expect(screen.getByText("Weight 2")).toBeInTheDocument();
  expect(screen.queryByLabelText("Topic weight")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Show weights/ }));
  expect((screen.getByLabelText("Topic weight") as HTMLInputElement).value).toBe("2");
});

test("toggles carry aria-expanded and change it without moving focus off an input", async () => {
  stub();
  await openDraft();

  const toggle = screen.getByRole("button", { name: /Show topics in Principles of chemistry/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  const title = screen.getByDisplayValue("Principles of chemistry");
  title.focus();
  expect(title).toHaveFocus();
  fireEvent.click(toggle);
  // Folding or opening a different row must leave the focused input alone.
  expect(title).toHaveFocus();
  expect(
    screen.getByRole("button", { name: /Hide topics in Principles of chemistry/ }),
  ).toHaveAttribute("aria-expanded", "true");
  // The same input node survives, so typing in it is not interrupted.
  expect(screen.getByDisplayValue("Principles of chemistry")).toBe(title);

  const all = screen.getByRole("button", { name: "Open all" });
  expect(all).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(all);
  expect(screen.getByRole("button", { name: "Fold all" })).toHaveAttribute("aria-expanded", "true");
});

test("the button says Fold all only while every sub-point is open too", async () => {
  stub();
  await openDraft();

  fireEvent.click(screen.getByRole("button", { name: "Open all" }));
  fireEvent.click(screen.getByRole("button", { name: /Hide sub-points of Atoms/ }));
  expect(screen.getByRole("button", { name: "Open all" })).toBeInTheDocument();
});

test("the grade scale shows the draft's value and a change saves", async () => {
  const puts = stub();
  await openDraft();

  const select = screen.getByLabelText("Grade scale") as HTMLSelectElement;
  expect(select.value).toBe("9-1");

  fireEvent.change(select, { target: { value: "A*-E" } });
  await waitFor(() => expect(puts).toHaveLength(1));
  expect((puts[0] as typeof DRAFT).grade_scale).toBe("A*-E");
});

test("a grade scale the AI could not recognise shows the placeholder", async () => {
  stub("review", { ...DRAFT, grade_scale: "" });
  await openDraft();

  const select = screen.getByLabelText("Grade scale") as HTMLSelectElement;
  expect(select.value).toBe("");
  expect(screen.getByRole("option", { name: "Choose a grade scale" })).toBeDisabled();
});

test("an unusual grade scale stays selectable", async () => {
  stub("review", { ...DRAFT, grade_scale: "A-G" });
  await openDraft();

  expect((screen.getByLabelText("Grade scale") as HTMLSelectElement).value).toBe("A-G");
});
