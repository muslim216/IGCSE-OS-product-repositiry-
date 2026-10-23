import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import SubmitHomeworkPage from "../student/SubmitHomeworkPage";
import { UploadProgress } from "../components/controls";
import { stubXhr } from "./fakeXhr";

/* Sending photos from a phone: a refused or failed hand-in leaves the files
   where they were, so the student presses the button again rather than
   picking every page a second time. */

const NOT_SENT = {
  submission_id: null,
  status: "not_submitted",
  submitted_at: null,
  finalized_at: null,
  total: null,
  total_max: null,
  marks: [],
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/my-submission") ? NOT_SENT : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/student/homework/4"]}>
        <Routes>
          <Route path="/student/homework/:assignmentId" element={<SubmitHomeworkPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a file over the limit is refused by name, before anything is sent, and stays selected", async () => {
  stubFetch();
  const sent = stubXhr(() => ({ status: 200, body: NOT_SENT }));
  renderPage();

  const input = await screen.findByLabelText("Photos or a scan of your answers");
  const big = new File(["%PDF"], "photo-12.pdf", { type: "application/pdf" });
  Object.defineProperty(big, "size", { value: 24 * 1024 * 1024 });
  fireEvent.change(input, { target: { files: [big] } });
  fireEvent.click(screen.getByRole("button", { name: "Submit work" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("photo-12.pdf is too big (24 MB). The limit is 20 MB per file.");
  expect(sent).toHaveLength(0);
  expect(screen.getByText("photo-12.pdf")).toBeInTheDocument();
});

test("a failed upload keeps the files so the retry needs no re-picking", async () => {
  stubFetch();
  let status = 500;
  const sent = stubXhr(() => ({ status, body: status === 500 ? { detail: "boom" } : NOT_SENT }));
  renderPage();

  const input = await screen.findByLabelText("Photos or a scan of your answers");
  const pdf = new File(["%PDF-1.4"], "answers.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [pdf] } });
  fireEvent.click(screen.getByRole("button", { name: "Submit work" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/went wrong on our side/);
  expect(screen.getByText("answers.pdf")).toBeInTheDocument();

  status = 200;
  await waitFor(() => expect(screen.getByRole("button", { name: "Submit work" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Submit work" }));
  await waitFor(() => expect(sent).toHaveLength(2));
  expect(sent[1].form.getAll("files")).toHaveLength(1);
});

test("progress shows as an accessible bar with a percentage, and can be cancelled", () => {
  const onCancel = vi.fn();
  render(<UploadProgress phase="sending" percent={42} onCancel={onCancel} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "42");
  expect(screen.getByText("42%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel upload" }));
  expect(onCancel).toHaveBeenCalled();
});

test("no number before the first real progress event", () => {
  render(<UploadProgress phase="sending" percent={null} onCancel={vi.fn()} />);
  expect(screen.getByText("Sending…")).toBeInTheDocument();
  expect(screen.queryByText(/%/)).toBeNull();
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
});

test("once every byte is sent it says Processing and offers no Cancel", () => {
  render(<UploadProgress phase="processing" percent={100} onCancel={vi.fn()} />);
  expect(screen.getByText("Processing…")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel upload" })).toBeNull();
});

test("a 401 refresh reads Reconnecting, not 0%", () => {
  render(<UploadProgress phase="reconnecting" percent={null} onCancel={vi.fn()} />);
  expect(screen.getByText("Reconnecting…")).toBeInTheDocument();
  expect(screen.queryByText("0%")).toBeNull();
});
