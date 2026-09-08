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

function stub(uploaded: boolean) {
  const puts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const state = (on: boolean) => ({
        subject_id: 7,
        subject_name: "Chemistry",
        uploaded: on,
        file_name: on ? "scheme-of-work.pdf" : null,
        file_mime: on ? "application/pdf" : null,
        uploaded_at: on ? "2026-09-01T10:00:00Z" : null,
      });

      if (method === "GET" && path === "/api/v1/subjects") return json(SUBJECTS);
      if (method === "GET" && path === "/api/v1/subjects/7/teaching-guidance")
        return json(state(uploaded || puts.length > 0));
      if (method === "PUT" && path === "/api/v1/subjects/7/teaching-guidance") {
        puts.push(path);
        return json(state(true));
      }
      if (method === "DELETE" && path === "/api/v1/subjects/7/teaching-guidance")
        return json(state(false));
      return new Response(JSON.stringify({ detail: `unstubbed ${method} ${path}` }), {
        status: 404,
      });
    }),
  );
  return puts;
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
  const puts = stub(false);
  renderPage();

  const input = (await screen.findByLabelText("Upload a document")) as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "scheme.pdf", { type: "application/pdf" })] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));

  await waitFor(() => expect(puts).toHaveLength(1));
  expect(await screen.findByText("scheme-of-work.pdf")).toBeTruthy();
});
