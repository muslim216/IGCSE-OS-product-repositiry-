import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import TeachingGuidancePage from "../tutor/TeachingGuidancePage";

/* The second per-subject document (2.5, AV-10). Three states have to read
   differently: nothing uploaded, a document on file, and a replacement in
   flight. "Nothing uploaded" is stated in words, never drawn as an empty row
   that looks like a broken one (PROD-2, UX-19). */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
];

/** A stub with server state, not a fixed answer per verb.
 *
 * Every mutation invalidates the query and the component re-reads through GET,
 * so a GET that ignores what PUT and DELETE did cannot express the flow this
 * page is: with a document on file, Remove would still show it (cubic). The
 * subject id is a capture so a request to the wrong subject 404s and surfaces
 * as a failure rather than as silence. */
function stub(uploaded: boolean) {
  const calls: { method: string; subject: number }[] = [];
  let onFile = uploaded;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const state = () => ({
        subject_id: 7,
        subject_name: "Chemistry",
        uploaded: onFile,
        file_name: onFile ? "scheme-of-work.pdf" : null,
        file_mime: onFile ? "application/pdf" : null,
        uploaded_at: onFile ? "2026-09-01T10:00:00Z" : null,
      });
      const guidance = /^\/api\/v1\/subjects\/(\d+)\/teaching-guidance$/.exec(path);

      if (method === "GET" && path === "/api/v1/subjects") return json(SUBJECTS);
      // Only the fixture subject exists. A request for any other id has to 404
      // here, or the stub cannot show a cross-subject write as the failure it
      // would be (cubic).
      if (guidance && Number(guidance[1]) === 7) {
        const subject = Number(guidance[1]);
        if (method !== "GET") calls.push({ method, subject });
        if (method === "PUT") onFile = true;
        if (method === "DELETE") onFile = false;
        return json(state());
      }
      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
  return calls;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TeachingGuidancePage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a subject with no guidance says so and offers an upload", async () => {
  stub(false);
  renderPage();

  expect(await screen.findByText(/No teaching guidance for this subject yet/)).toBeTruthy();
  expect(screen.getByLabelText("Upload a document")).toBeTruthy();
  expect(screen.queryByText("Remove")).toBeNull();
});

test("a document on file is named, openable and replaceable", async () => {
  stub(true);
  renderPage();

  expect(await screen.findByText("scheme-of-work.pdf")).toBeTruthy();
  expect(screen.getByText("Open")).toBeTruthy();
  expect(screen.getByText("Remove")).toBeTruthy();
  // One document per subject: the control replaces, it does not add a second.
  expect(screen.getByLabelText("Replace it")).toBeTruthy();
});

test("uploading sends one PUT and shows the stored document", async () => {
  const calls = stub(false);
  renderPage();

  const input = (await screen.findByLabelText("Upload a document")) as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "scheme.pdf", { type: "application/pdf" })] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));

  await waitFor(() => expect(calls).toEqual([{ method: "PUT", subject: 7 }]));
  expect(await screen.findByText("scheme-of-work.pdf")).toBeTruthy();
});

test("removing a document leaves the absent state, not the old one", async () => {
  const calls = stub(true);
  renderPage();

  fireEvent.click(await screen.findByText("Remove"));

  await waitFor(() => expect(calls).toEqual([{ method: "DELETE", subject: 7 }]));
  expect(await screen.findByText(/No teaching guidance for this subject yet/)).toBeTruthy();
  expect(screen.queryByText("scheme-of-work.pdf")).toBeNull();
});
