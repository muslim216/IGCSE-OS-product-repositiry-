import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

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
