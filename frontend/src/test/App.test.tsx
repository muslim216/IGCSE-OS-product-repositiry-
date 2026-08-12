import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("unauthenticated users see the login page", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("avora")).toBeInTheDocument();
  expect(screen.getByText("Sign in with your email or username.")).toBeInTheDocument();
});

/** A signed-in tutor with an empty roster, landing at the / or /tutor/today. */
function stubTutorHome() {
  const tutorUser = { id: 1, email: "t@example.com", username: null, role: "tutor", name: "T" };
  const emptyToday = {
    classes: [],
    lessons: [],
    review_count: 0,
    class_count: 0,
    joined_student_count: 0,
    classes_with_evidence: 0,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me")) return json(tutorUser);
      if (url.includes("/narrative")) {
        return json({ text: null, generated_at: null, prompt_version: null });
      }
      if (url.includes("/api/v1/today")) return json(emptyToday);
      return json([]);
    }),
  );
  localStorage.setItem(
    "igcse-os-tokens",
    JSON.stringify({ access_token: "t", refresh_token: "r", token_type: "bearer" }),
  );
}

function renderAppAt(path: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

test("a signed-in tutor's / lands on the Today home, not the old classes list", async () => {
  stubTutorHome();
  renderAppAt("/");
  expect(await screen.findByText("You haven't set up a class yet.")).toBeInTheDocument();
});

test("/tutor/today, an old bookmark, redirects to the new home rather than 404ing", async () => {
  stubTutorHome();
  renderAppAt("/tutor/today");
  expect(await screen.findByText("You haven't set up a class yet.")).toBeInTheDocument();
});
