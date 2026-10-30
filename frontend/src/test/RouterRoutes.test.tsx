import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

function renderApp(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

test("a signed-out deep link to a tutor page goes to sign-in", async () => {
  renderApp("/tutor/review");
  expect(await screen.findByRole("heading", { name: /Welcome back to avora/ })).toBeInTheDocument();
});

test("a signed-out deep link to a student page goes to sign-in", async () => {
  renderApp("/student/homework/3");
  expect(await screen.findByRole("heading", { name: /Welcome back to avora/ })).toBeInTheDocument();
});

test("an unknown path shows the 404 page", async () => {
  renderApp("/no/such/page");
  expect(
    await screen.findByRole("heading", { name: /This page doesn't exist/ }),
  ).toBeInTheDocument();
});

test("a path with a backslash host-like prefix stays inside the app", async () => {
  renderApp("/%5Cexample.invalid");
  expect(
    await screen.findByRole("heading", { name: /This page doesn't exist/ }),
  ).toBeInTheDocument();
});

// No screen passes a user-supplied value to Link or navigate, so this guards the
// router itself: a doubled slash or backslash must never be treated as an in-app
// path (which would later be read back as another site's address).
test.each(["/\\example.invalid", "\\\\example.invalid", "//example.invalid"])(
  "navigate(%j) never lands on an in-app path that starts with two separators",
  (target) => {
    function Go() {
      const navigate = useNavigate();
      // Refusing the target (it throws) is as safe as staying on a clean path.
      const go = () => {
        try {
          navigate(target);
        } catch {
          /* refused */
        }
      };
      return <button onClick={go}>go</button>;
    }
    function Where() {
      return <p data-testid="where">{useLocation().pathname}</p>;
    }
    render(
      <MemoryRouter initialEntries={["/start"]}>
        <Go />
        <Where />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(screen.getByTestId("where").textContent).not.toMatch(/^[\\/]{2}/);
  },
);
