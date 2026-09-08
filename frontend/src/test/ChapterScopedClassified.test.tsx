import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import AssignmentCreatePage from "../tutor/AssignmentCreatePage";

/* Chapter-scoped classifieds (3.1, AV-20/AV-21). What has to hold on screen:
   a booklet is filed under the chapter the tutor is starting, the notes that
   travel with it reach the server, and — because those notes are marking
   context the AI will act on — a correction to a reused booklet lands *before*
   work is set from it. */

const SUBJECT = {
  id: 7,
  exam_board: "Edexcel IGCSE",
  code: "4CH1",
  name: "Chemistry",
  grade_scale: "9-1",
};

// Teaching order, deliberately not code order: a tutor may teach chapter 4
// before chapter 3, so a list sorted by code would prove nothing.
const CHAPTERS = [
  { id: 21, code: "2", title: "Bonding", position: 1 },
  { id: 22, code: "1", title: "States of matter", position: 2 },
];

const BOOKLET = {
  id: 55,
  subject_id: 7,
  title: "Bonding classified",
  file_name: "bonding.pdf",
  mark_scheme_name: null,
  chapter_id: 21,
  notes: "Accept either sign convention.",
};

function stub({ classifieds = [] as (typeof BOOKLET)[], holdPatch = false } = {}) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  /** Resolves the held PATCH, so a test can prove the assignment is not created
   *  until the booklet's notes have actually landed. */
  let releasePatch = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

      if (method === "GET" && path === "/api/v1/groups/3")
        return json({
          id: 3,
          name: "Chem Y10",
          subject: SUBJECT,
          members: [],
          member_count: 0,
          students_with_evidence: 0,
          published_assignment_count: 0,
          awaiting_review_count: 0,
          next_lesson: null,
        });
      if (method === "GET" && path === "/api/v1/subjects/7/chapters") return json(CHAPTERS);
      if (method === "GET" && path === "/api/v1/classifieds") return json(classifieds);

      if (method === "POST" && path === "/api/v1/assignments/upload") {
        const form = init?.body as FormData;
        calls.push({
          method,
          path,
          body: { chapter_id: form.get("chapter_id"), notes: form.get("notes") },
        });
        return json(
          { id: 9, group_id: 3, title: "paper", status: "extracting", questions: [] },
          201,
        );
      }
      if (method === "PATCH" && path === "/api/v1/classifieds/55") {
        const body = JSON.parse(String(init?.body));
        calls.push({ method, path, body });
        const answer = () => json({ ...BOOKLET, ...body });
        if (!holdPatch) return answer();
        return new Promise<Response>((resolve) => {
          releasePatch = () => resolve(answer());
        });
      }
      if (method === "POST" && path === "/api/v1/assignments") {
        calls.push({ method, path, body: JSON.parse(String(init?.body)) });
        return json(
          { id: 9, group_id: 3, title: "Homework", status: "extracting", questions: [] },
          201,
        );
      }
      return json({ detail: `unstubbed ${method} ${path}` }, 404);
    }),
  );
  return { calls, releasePatch: () => releasePatch() };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/groups/3/homework/new"]}>
        <Routes>
          <Route path="/tutor/groups/:groupId/homework/new" element={<AssignmentCreatePage />} />
          <Route path="/tutor/assignments/:id" element={<p>Assignment page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openDetails() {
  fireEvent.click(await screen.findByRole("button", { name: /Optional details/ }));
}

function dropFile() {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["%PDF-1.4"], "bonding.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
}

afterEach(() => vi.unstubAllGlobals());

test("a new paper is filed under a chapter, in teaching order, with its notes", async () => {
  const { calls } = stub();
  renderPage();
  dropFile();
  await openDetails();

  const picker = await screen.findByLabelText(/Chapter this paper belongs to/);
  expect(Array.from(picker.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
    "Not set",
    "2 — Bonding",
    "1 — States of matter",
  ]);

  fireEvent.change(picker, { target: { value: "22" } });
  fireEvent.change(screen.getByLabelText(/Marking notes for this paper/), {
    target: { value: "Method marks stand even with the wrong answer." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set homework" }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].body).toEqual({
    chapter_id: "22",
    notes: "Method marks stand even with the wrong answer.",
  });
});

test("the screen does not claim marking already reads the notes", async () => {
  stub();
  renderPage();
  dropFile();
  await openDetails();

  // PROD-1: nothing marks with these until 3.2's assembler, and the mark scheme
  // is absolute whatever they say (AV-94) — so the copy says both.
  const hint = await screen.findByText(/Marking does not read these yet/);
  expect(hint.textContent).toMatch(/mark scheme always wins/i);
});

test("reusing a booklet shows its own chapter and notes", async () => {
  stub({ classifieds: [BOOKLET] });
  renderPage();

  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "55" } });
  await openDetails();

  await waitFor(() =>
    expect(
      (screen.getByLabelText(/Chapter this paper belongs to/) as HTMLSelectElement).value,
    ).toBe("21"),
  );
  expect((screen.getByLabelText(/Marking notes for this paper/) as HTMLTextAreaElement).value).toBe(
    BOOKLET.notes,
  );
});

test("a correction to a reused booklet is saved before work is set from it", async () => {
  const { calls, releasePatch } = stub({ classifieds: [BOOKLET], holdPatch: true });
  renderPage();

  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "55" } });
  await openDetails();
  await waitFor(() =>
    expect(
      (screen.getByLabelText(/Marking notes for this paper/) as HTMLTextAreaElement).value,
    ).toBe(BOOKLET.notes),
  );
  fireEvent.change(screen.getByLabelText(/Marking notes for this paper/), {
    target: { value: "Only the 2019 convention now." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set homework" }));

  // The PATCH is held open. Homework created against stale notes would be
  // marked against them, so the assignment must not exist yet — issuing both
  // requests together would be a race, not a sequence.
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0]).toMatchObject({
    method: "PATCH",
    body: { chapter_id: 21, notes: "Only the 2019 convention now." },
  });

  releasePatch();
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(calls[1].path).toBe("/api/v1/assignments");
});

test("an untouched booklet is not rewritten", async () => {
  const { calls } = stub({ classifieds: [BOOKLET] });
  renderPage();

  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "55" } });
  await openDetails();
  await waitFor(() =>
    expect(
      (screen.getByLabelText(/Marking notes for this paper/) as HTMLTextAreaElement).value,
    ).toBe(BOOKLET.notes),
  );
  fireEvent.click(screen.getByRole("button", { name: "Set homework" }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe("/api/v1/assignments");
});
