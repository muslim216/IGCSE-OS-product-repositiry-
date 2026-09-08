import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import MarkingRulesPage from "../tutor/MarkingRulesPage";

/* The AI marking agreement (2.6, AV-75/AV-111). What has to hold on screen:
   an unset subject says so rather than looking unfinished, a draft belongs to
   the subject it was typed for, and the page never claims to decide when a mark
   counts (AV-25) or that marking already reads these rules (PROD-1). */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
  { id: 8, exam_board: "Edexcel IGCSE", code: "4BI1", name: "Biology", grade_scale: "9-1" },
];

function stub(initial: Record<number, string> = {}) {
  const saved: { subject: number; rules: string }[] = [];
  const state = { ...initial };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const match = /^\/api\/v1\/subjects\/(\d+)\/marking-rules$/.exec(path);

      if (method === "GET" && path === "/api/v1/subjects") return json(SUBJECTS);
      if (match) {
        const subject = Number(match[1]);
        const known = SUBJECTS.find((s) => s.id === subject);
        if (!known)
          return new Response(JSON.stringify({ detail: "no such subject" }), { status: 404 });
        if (method === "PUT") {
          const rules = JSON.parse(String(init?.body)).rules as string;
          saved.push({ subject, rules });
          state[subject] = rules;
        }
        const rules = state[subject] ?? "";
        return json({
          subject_id: subject,
          subject_name: known.name,
          rules,
          configured: rules.length > 0,
        });
      }
      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
  return saved;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MarkingRulesPage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("an unset subject says so, and says leaving it empty is fine", async () => {
  stub();
  renderPage();

  expect(await screen.findByText(/Nothing set for this subject/)).toBeTruthy();
  // AV-87: skippable by design, so the empty box is not an unfinished step.
  expect(screen.getByText(/Leaving it empty is fine/)).toBeTruthy();
});

test("the page does not claim to decide when a mark counts, or that marking reads it", async () => {
  stub();
  renderPage();

  await screen.findByLabelText("Marking rules for Chemistry");
  // AV-25 is not reachable from this screen, and nothing marks with these yet.
  // Matched on the paragraph itself: the sentence is split by <strong> tags,
  // and ancestors match a textContent test too.
  const paragraphs = Array.from(document.querySelectorAll("p")).map((p) => p.textContent ?? "");
  expect(paragraphs.some((t) => /never.*when.*a mark counts/is.test(t))).toBe(true);
  expect(paragraphs.some((t) => /does not read them yet/i.test(t))).toBe(true);
});

test("saving sends the draft for the selected subject", async () => {
  const saved = stub();
  renderPage();

  const box = await screen.findByLabelText("Marking rules for Chemistry");
  fireEvent.change(box, { target: { value: "Award method marks." } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(saved).toEqual([{ subject: 7, rules: "Award method marks." }]));
});

test("switching subject loads that subject's own rules, never the other's draft", async () => {
  // AV-75: no account-wide layer — each subject stands alone.
  stub({ 7: "Chemistry rules.", 8: "" });
  renderPage();

  expect(await screen.findByDisplayValue("Chemistry rules.")).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "8" } });

  await screen.findByLabelText("Marking rules for Biology");
  expect(screen.queryByDisplayValue("Chemistry rules.")).toBeNull();
  expect(await screen.findByText(/Nothing set for this subject/)).toBeTruthy();
});

test("a draft cannot be saved onto the subject it was not typed for", async () => {
  // The window between switching subject and its rules arriving: `draft` still
  // holds the previous subject's text, and the editor must not be savable until
  // what is loaded matches what is selected.
  const saved = stub({ 7: "Chemistry rules.", 8: "Biology rules." });
  renderPage();

  await screen.findByDisplayValue("Chemistry rules.");
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "8" } });
  await screen.findByDisplayValue("Biology rules.");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  // Nothing to save — the loaded rules and the draft agree — and certainly not
  // Chemistry's text under Biology's id.
  expect(saved).toEqual([]);
});
