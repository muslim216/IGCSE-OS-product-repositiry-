import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ChangePasswordForm from "../components/ChangePasswordForm";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChangePasswordForm />
    </QueryClientProvider>,
  );
}

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirm } });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
}

test("a mismatched confirmation is refused without calling the server", () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  renderForm();
  fill("old-password", "new-password-1", "new-password-2");
  expect(screen.getByText("The two passwords don't match.")).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("success stores the fresh access token and says so", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () => new Response(JSON.stringify({ access_token: "fresh", token_type: "bearer" })),
    ),
  );
  renderForm();
  fill("old-password", "new-password-1", "new-password-1");
  await screen.findByText(/Password changed/);
  const stored = localStorage.getItem("avora-tokens") ?? "";
  expect(JSON.parse(stored).access_token).toBe("fresh");
  expect(stored).not.toContain("refresh_token");
});

test("a wrong current password shows the server's plain message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Your current password is incorrect." }), {
          status: 400,
        }),
    ),
  );
  renderForm();
  fill("wrong", "new-password-1", "new-password-1");
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("incorrect"));
});

test("a wrong current password puts focus back on that field", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Your current password is incorrect." }), {
          status: 400,
        }),
    ),
  );
  renderForm();
  fill("wrong", "new-password-1", "new-password-1");
  await screen.findByRole("alert");
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByLabelText("Current password")),
  );
});

test("the mismatch message clears when the confirmation is edited", () => {
  vi.stubGlobal("fetch", vi.fn());
  renderForm();
  fill("old-password", "new-password-1", "new-password-2");
  fireEvent.change(screen.getByLabelText("Confirm new password"), {
    target: { value: "new-password-1" },
  });
  expect(screen.queryByText("The two passwords don't match.")).toBeNull();
});

test("the show toggle reveals the fields", () => {
  vi.stubGlobal("fetch", vi.fn());
  renderForm();
  const toggle = screen.getByRole("button", { name: "Show passwords" });
  expect(toggle.getAttribute("aria-pressed")).toBe("false");
  fireEvent.click(toggle);
  expect(screen.getByLabelText("Current password").getAttribute("type")).toBe("text");
  expect(screen.getByRole("button", { name: "Show passwords" }).getAttribute("aria-pressed")).toBe(
    "true",
  );
});
