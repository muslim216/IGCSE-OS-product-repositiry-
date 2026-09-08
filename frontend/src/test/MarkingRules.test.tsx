import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import MarkingRulesPage from "../tutor/MarkingRulesPage";
import type { MarkingRules } from "../api/markingRules";

/* The AI marking agreement (2.6, AV-75/AV-111). What has to hold on screen:
   an unset subject says so rather than looking unfinished, a draft belongs to
   the subject it was typed for, and the page never claims to decide when a mark
   counts (AV-25) or that marking already reads these rules (PROD-1). */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
  { id: 8, exam_board: "Edexcel IGCSE", code: "4BI1", name: "Biology", grade_scale: "9-1" },
];

function stub(initial: Record<number, string> = {}, options: { hold?: number } = {}) {
  const saved: { subject: number; rules: string }[] = [];
  const state = { ...initial };
  /** Requests for this subject never resolve, which is the window between
   *  switching subject and its rules arriving. */
  const held = options.hold;
  /** Change what the server holds, as another session would. */
  const setStored = (subject: number, rules: string) => {
    state[subject] = rules;
  };
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
        if (subject === held) return new Promise<Response>(() => {});
        const known = SUBJECTS.find((s) => s.id === subject);
        if (!known)
          return new Response(JSON.stringify({ detail: "no such subject" }), { status: 404 });
        if (method === "PUT") {
          // The API trims before storing, so whitespace-only rules come back as
          // no rules at all — the case this stub has to be faithful about.
          const rules = (JSON.parse(String(init?.body)).rules as string).trim();
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
  return { saved, setStored };
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
  const { saved } = stub();
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

test("mid-switch, there is nothing to save and no text from the old subject", async () => {
  // Biology's request never resolves, so this sits in the window between
  // selecting it and its rules arriving. Chemistry's text and the Save button
  // must both be gone: a click there would write one subject's rules onto
  // another.
  //
  // What makes that true is the query key carrying the subject — cubic was
  // right that this cannot fail with the `subject_id !== selected` condition
  // removed, and the honest reading is that the condition is defence in depth,
  // not the mechanism. The behaviour is still worth pinning: it is what breaks
  // if someone makes this query keep previous data across the switch.
  const { saved } = stub({ 7: "Chemistry rules.", 8: "Biology rules." }, { hold: 8 });
  renderPage();

  await screen.findByDisplayValue("Chemistry rules.");
  fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "8" } });

  await waitFor(() => expect(screen.queryByDisplayValue("Chemistry rules.")).toBeNull());
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(saved).toEqual([]);
});

test("a refetch does not overwrite what the tutor has typed", async () => {
  // A window regaining focus is enough to refetch. Copying the stored text in
  // again would discard unsaved edits mid-sentence (CodeRabbit).
  const { setStored } = stub({ 7: "Stored rules." });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MarkingRulesPage />
    </QueryClientProvider>,
  );

  const box = await screen.findByDisplayValue("Stored rules.");
  fireEvent.change(box, { target: { value: "Half-written new rules" } });

  // The stored text changes under them, as a second session would change it.
  // Without the guard the effect copies it straight over the draft.
  setStored(7, "Rules edited in another tab.");
  await act(async () => {
    await client.refetchQueries({ queryKey: ["marking-rules", 7] });
  });
  // The new value has reached the cache, so any effect that hydrates from it
  // has had its chance — without the guard the textarea now reads the server's
  // text instead of the tutor's.
  await waitFor(() =>
    expect((client.getQueryData(["marking-rules", 7]) as MarkingRules).rules).toBe(
      "Rules edited in another tab.",
    ),
  );

  expect(screen.getByDisplayValue("Half-written new rules")).toBeTruthy();
});

test("saving whitespace-only rules leaves the box cleared, not still full of spaces", async () => {
  // The server normalizes whitespace to no rules at all. The per-subject
  // hydration guard ignores query updates, so without adopting the save's own
  // response the editor kept showing the discarded whitespace with Save still
  // enabled (cubic).
  const { saved } = stub({ 7: "Stored rules." });
  renderPage();

  const box = (await screen.findByDisplayValue("Stored rules.")) as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: "   \n  " } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(saved).toHaveLength(1));
  await waitFor(() => expect(box.value).toBe(""));
  expect(await screen.findByText(/Nothing set for this subject/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
