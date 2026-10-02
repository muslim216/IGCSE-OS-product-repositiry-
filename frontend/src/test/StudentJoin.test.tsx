import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import JoinPage from "../auth/JoinPage";

/* The student's half of ParentJoin.test.tsx: a class invite that could not be
   checked is not an invalid one, so it offers a retry instead of sending the
   student back to their tutor for a new link. */

const PREVIEW = {
  kind: "student_join",
  group_name: "Year 10 Chemistry",
  subject_name: "Chemistry",
  tutor_name: "Layla Haddad",
  student_name: null,
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function stubPreview(respond: () => Response) {
  const preview = vi.fn(respond);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/auth/invites/abc123")) return preview();
      return json(null);
    }),
  );
  return preview;
}

function renderJoin() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={["/join/abc123"]}>
          <Routes>
            <Route path="/join/:code" element={<JoinPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("no connection is not an invalid invitation, and the check can be retried", async () => {
  const preview = stubPreview(() => {
    throw new TypeError("Failed to fetch");
  });
  renderJoin();

  expect(await screen.findByText("We couldn't check this invitation.")).toBeInTheDocument();
  expect(screen.queryByText("This invitation isn't valid")).not.toBeInTheDocument();

  preview.mockImplementation(() => json(PREVIEW));
  fireEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByText("Join Year 10 Chemistry")).toBeInTheDocument();
});

test("a server error is not an invalid invitation", async () => {
  stubPreview(() => json({ detail: "Internal Server Error" }, 500));
  renderJoin();

  expect(await screen.findByText("We couldn't check this invitation.")).toBeInTheDocument();
  expect(screen.queryByText("This invitation isn't valid")).not.toBeInTheDocument();
});

test("a code the server refuses is an invalid invitation", async () => {
  stubPreview(() => json({ detail: "This invite link is not valid" }, 404));
  renderJoin();

  expect(await screen.findByText("This invitation isn't valid")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
});
