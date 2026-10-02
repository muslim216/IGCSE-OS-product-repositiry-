import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import ParentJoinPage from "../auth/ParentJoinPage";

/* The first screen a parent sees from the tutor's link. They have nothing to
   go on but what it says, so "this invitation isn't valid" has to mean the
   server refused the code — never that the request got no answer. Said
   wrongly, it sends them back to the tutor for a new link they do not need. */

const PREVIEW = {
  kind: "parent_link",
  group_name: null,
  subject_name: null,
  tutor_name: null,
  student_name: "Sara",
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** Answers the invite preview with `respond`, which a test can swap mid-way to
 *  model a retry that succeeds. Nothing else on the page calls the network
 *  while signed out. */
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
        <MemoryRouter initialEntries={["/parent-join/abc123"]}>
          <Routes>
            <Route path="/parent-join/:code" element={<ParentJoinPage />} />
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
  expect(screen.getByText(/Can't reach avora right now/)).toBeInTheDocument();
  expect(screen.queryByText("This invitation isn't valid")).not.toBeInTheDocument();

  preview.mockImplementation(() => json(PREVIEW));
  fireEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByText("Follow Sara's progress")).toBeInTheDocument();
});

test("a server error is not an invalid invitation", async () => {
  stubPreview(() => json({ detail: "Internal Server Error" }, 500));
  renderJoin();

  expect(await screen.findByText("We couldn't check this invitation.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  expect(screen.queryByText("This invitation isn't valid")).not.toBeInTheDocument();
});

test.each([
  [404, "This invite link is not valid"],
  [410, "This invite link has already been used — ask for a new one"],
])("a code the server refuses (%i) is an invalid invitation", async (status, detail) => {
  stubPreview(() => json({ detail }, status));
  renderJoin();

  expect(await screen.findByText("This invitation isn't valid")).toBeInTheDocument();
  // Asking again gives the same answer, so nothing offers to.
  expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
});

test("a student's class invite opened as a parent link is not valid here", async () => {
  stubPreview(() =>
    json({
      kind: "student_join",
      group_name: "Chem Y10",
      subject_name: "Chemistry",
      tutor_name: "Ms Ali",
      student_name: null,
    }),
  );
  renderJoin();

  expect(await screen.findByText("This invitation isn't valid")).toBeInTheDocument();
});
