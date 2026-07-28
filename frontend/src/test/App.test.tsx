import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

function renderAt(path: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

test("unauthenticated users see the login page", async () => {
  renderAt("/login");
  expect(await screen.findByText("IGCSE Student OS")).toBeInTheDocument();
  expect(screen.getByText("Sign in with your email or username.")).toBeInTheDocument();
});

test("the root path explains the product instead of redirecting to a form", async () => {
  renderAt("/");
  expect(
    await screen.findByText("Know exactly how ready each student is"),
  ).toBeInTheDocument();
  // Both ways in are offered, and the invite-only path is stated rather than
  // left as a dead end for students and parents.
  expect(screen.getByRole("link", { name: "Start as a tutor" })).toHaveAttribute(
    "href",
    "/signup",
  );
  expect(
    screen.getByText(/Students and parents join with an invite link/),
  ).toBeInTheDocument();
});
