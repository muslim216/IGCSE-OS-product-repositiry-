import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentDetailPage from "../tutor/StudentDetailPage";
import { axeViolations } from "./axe";

afterEach(() => vi.unstubAllGlobals());

test.each(["progress", "work", "notes", "about"])("the %s tab has no axe violations", async (t) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      const body =
        url.pathname === "/api/v1/readiness/students/2"
          ? { student_id: 2, student_name: "Sara", subjects: [] }
          : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/tutor/students/2?tab=${t}`]}>
        <Routes>
          <Route path="/tutor/students/:studentId" element={<StudentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("tab", { name: "Progress" });
  await screen.findByRole("tabpanel");
  expect(await axeViolations(container)).toEqual([]);
});
