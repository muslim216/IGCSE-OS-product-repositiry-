import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import RenameStudent from "../tutor/RenameStudent";

afterEach(() => vi.unstubAllGlobals());

function renderIt(name = "Sara") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (n: string) => (
    <QueryClientProvider client={client}>
      <RenameStudent studentId={7} name={n} />
    </QueryClientProvider>
  );
  const view = render(ui(name));
  return { rerender: (n: string) => view.rerender(ui(n)) };
}

const input = () => screen.getByLabelText("Student's name") as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Save name" }) as HTMLButtonElement;

test("saves with a PATCH to the student and keeps saying Saved after the name prop changes", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 7, name: "Sara Ahmed" })));
  vi.stubGlobal("fetch", fetchMock);
  const { rerender } = renderIt();
  expect(save().disabled).toBe(true);
  fireEvent.change(input(), { target: { value: " Sara Ahmed " } });
  expect(save().disabled).toBe(false);
  fireEvent.click(save());
  await screen.findByText("Saved.");
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/students/7");
  expect(init.method).toBe("PATCH");
  expect(JSON.parse(String(init.body))).toEqual({ name: "Sara Ahmed" });
  // The refetch brings the new name in; the confirmation must survive it.
  rerender("Sara Ahmed");
  expect(screen.getByText("Saved.")).toBeTruthy();
  expect(input().value).toBe("Sara Ahmed");
});

test("an unsaved edit is not overwritten by a refetched name", () => {
  vi.stubGlobal("fetch", vi.fn());
  const { rerender } = renderIt();
  fireEvent.change(input(), { target: { value: "Sarah" } });
  rerender("Sara B");
  expect(input().value).toBe("Sarah");
});

test("an edit reverted to the shown name lets a refetched name in again", () => {
  vi.stubGlobal("fetch", vi.fn());
  const { rerender } = renderIt();
  fireEvent.change(input(), { target: { value: "Sarah" } });
  fireEvent.change(input(), { target: { value: "Sara" } });
  rerender("Sara B");
  expect(input().value).toBe("Sara B");
});

test("a refused rename shows the error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ detail: "Student not found" }), { status: 404 }),
    ),
  );
  renderIt();
  fireEvent.change(input(), { target: { value: "Other" } });
  fireEvent.click(save());
  await waitFor(() => expect(screen.getByText(/We couldn.t find that/)).toBeTruthy());
});
