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

function stub() {
  const puts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const upload = { id: 1, title: "Chemistry 4CH1", file_name: "s.pdf", status: "review" };
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

async function openDraft() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SyllabusUploadPage />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText("Chemistry 4CH1"));
  await screen.findByText("2 chapters, 4 topics");
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

  await waitFor(() => expect(puts.length).toBe(1));
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
  await waitFor(() => expect(puts.length).toBe(1));
  expect((puts[0] as typeof DRAFT).level).toBe("a_level");
});
