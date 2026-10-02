import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GroupsPage from "../tutor/GroupsPage";

/* Creating a class. A subject list that fails to load is retried where it
   failed: the old advice, "refresh the page", also threw away the class name
   the tutor had just typed. */

afterEach(() => vi.unstubAllGlobals());

test("a failed subject list is retried in place, keeping the typed class name", async () => {
  let subjectsFail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/v1/subjects")
        return subjectsFail
          ? new Response(JSON.stringify({ detail: "boom" }), { status: 500 })
          : new Response(
              JSON.stringify([
                { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry" },
              ]),
              { status: 200 },
            );
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GroupsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  fireEvent.click((await screen.findAllByRole("button", { name: /New class/ }))[0]);
  fireEvent.change(screen.getByLabelText("Class name"), {
    target: { value: "Chemistry — Year 10" },
  });
  expect(await screen.findByText("Subjects didn't load.")).toBeInTheDocument();

  subjectsFail = false;
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByRole("option", { name: "Chemistry — Edexcel IGCSE 4CH1" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Class name")).toHaveValue("Chemistry — Year 10");
  expect(screen.queryByText("Subjects didn't load.")).not.toBeInTheDocument();
});
