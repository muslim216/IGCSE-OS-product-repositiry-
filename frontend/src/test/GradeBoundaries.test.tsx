import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import GradeBoundariesPage from "../tutor/GradeBoundariesPage";
import type { GradeBoundaries } from "../api/gradeBoundaries";

/* The grade-boundary editor keeps the tutor's draft through a refetch. Every
   predicted grade in the product is read through these numbers, so losing a
   half-edited list to a window regaining focus is losing work that matters. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
];

function stub() {
  let stored = [
    { grade: "9", min: 90 },
    { grade: "8", min: 80 },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (path === "/api/v1/subjects") return json(SUBJECTS);
      if (path === "/api/v1/subjects/7/grade-boundaries")
        return json({
          subject_id: 7,
          subject_name: "Chemistry",
          grade_scale: "9-1",
          source: "organization",
          boundaries: stored,
        });
      return new Response(JSON.stringify({ detail: `unstubbed ${path}` }), { status: 404 });
    }),
  );
  /** Change what the server holds, as a colleague's save in another tab would. */
  return {
    setStored: (next: typeof stored) => {
      stored = next;
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

test("a refetch does not overwrite boundaries the tutor has edited but not saved", async () => {
  const { setStored } = stub();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GradeBoundariesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const nine = await screen.findByLabelText("Minimum percentage for grade 9");
  fireEvent.change(nine, { target: { value: "88" } });

  setStored([
    { grade: "9", min: 95 },
    { grade: "8", min: 85 },
  ]);
  await act(async () => {
    await client.refetchQueries({ queryKey: ["grade-boundaries", 7] });
  });
  // The server's new value has reached the cache, so a hydrating effect has
  // had its chance to copy it over the draft.
  await waitFor(() =>
    expect(
      (client.getQueryData(["grade-boundaries", 7]) as GradeBoundaries).boundaries[0].min,
    ).toBe(95),
  );

  expect(screen.getByLabelText<HTMLInputElement>("Minimum percentage for grade 9").value).toBe(
    "88",
  );
});
