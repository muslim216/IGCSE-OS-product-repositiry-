import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function stub(status = "review") {
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
          error: null,
          subject_id: null,
          created_at: "2026-06-01",
          draft: DRAFT,
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
      <SyllabusUploadPage />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));
  await screen.findByText(expectSummary);
}

afterEach(() => vi.unstubAllGlobals());

test("the draft renders as chapters holding their own topics", async () => {
  stub();
  await openDraft();

  expect(screen.getByDisplayValue("Principles of chemistry")).toBeTruthy();
  expect(screen.getByDisplayValue("Inorganic chemistry")).toBeTruthy();
  // Sub-topics stay under their parent topic, inside the parent's chapter.
  expect(screen.getByDisplayValue("Isotopes")).toBeTruthy();
});

test("editing a topic keeps it in its chapter", async () => {
  const puts = stub();
  await openDraft();

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
  // "Retry extraction" on screen — one click from re-running the AI over the
  // tutor's own corrections (cubic).
  const puts = stub("extraction_failed");
  await openDraft();
  expect(screen.getByText("Retry extraction")).toBeTruthy();

  fireEvent.change(screen.getByDisplayValue("Principles of chemistry"), {
    target: { value: "Principles" },
  });

  await waitFor(() => expect(puts).toHaveLength(1));
  await waitFor(() => expect(screen.queryByText("Retry extraction")).toBeNull());
  // The tutor's edit is still on screen, not replaced by the server echo.
  expect(screen.getByDisplayValue("Principles")).toBeTruthy();
});
