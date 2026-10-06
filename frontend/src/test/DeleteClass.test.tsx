import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { DeleteClass } from "../tutor/DeleteClass";

function Landed() {
  const state = useLocation().state as { notice?: string } | null;
  return <p>All classes. {state?.notice}</p>;
}

function setup(respond: () => Response = () => new Response(null, { status: 204 })) {
  const fetch = vi.fn(async () => respond());
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tutor/groups/7/homework"]}>
        <Routes>
          <Route
            path="/tutor/groups/:id/homework"
            element={<DeleteClass groupId={7} name="Year 10 Chemistry" />}
          />
          <Route path="/tutor/classes" element={<Landed />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetch, invalidate };
}

afterEach(() => vi.unstubAllGlobals());

test("the dialog says what will and will not happen, and Cancel has focus", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Delete class" }));

  const dialog = screen.getByRole("dialog", { name: "Delete Year 10 Chemistry?" });
  expect(dialog).toHaveTextContent("will disappear for you and for its students");
  expect(dialog).toHaveTextContent("lessons, reminders and messages will stop");
  expect(dialog).toHaveTextContent("Marks and history are kept");
  expect(dialog).toHaveTextContent("readiness does not change");
  expect(dialog).toHaveTextContent("can’t be undone from the app");
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
});

test("Cancel closes the dialog and asks nothing of the server", async () => {
  const { fetch } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Delete class" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(fetch).not.toHaveBeenCalled();
});

test("confirming deletes the class, goes to All classes, and refreshes what lists classes", async () => {
  const { fetch, invalidate } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Delete class" }));
  // Two buttons carry this name once the dialog is open: the one on the page
  // and the one in the dialog; the dialog's is the confirm.
  const buttons = screen.getAllByRole("button", { name: "Delete class" });
  fireEvent.click(buttons[buttons.length - 1]);

  expect(await screen.findByText(/All classes\./)).toHaveTextContent(
    "Year 10 Chemistry was deleted.",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("/api/v1/groups/7");
  expect(init.method).toBe("DELETE");
  const refreshed = invalidate.mock.calls.map((c) => (c[0]?.queryKey as string[])[0]);
  for (const key of ["groups", "today", "onboarding", "homework", "students", "review-queue"]) {
    expect(refreshed).toContain(key);
  }
});

test("a failure keeps the dialog open and says so", async () => {
  setup(() => new Response(JSON.stringify({ detail: "Group not found" }), { status: 404 }));
  fireEvent.click(screen.getByRole("button", { name: "Delete class" }));
  const buttons = screen.getAllByRole("button", { name: "Delete class" });
  fireEvent.click(buttons[buttons.length - 1]);

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});
