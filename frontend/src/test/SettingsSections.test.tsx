import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SettingsPage from "../tutor/SettingsPage";

// Marking rules stands in for any section that crashes while rendering.
const state = vi.hoisted(() => ({ broken: true }));
vi.mock("../tutor/MarkingRulesPage", () => ({
  default: () => {
    if (state.broken) throw new Error("boom");
    return <h2>Marking rules recovered</h2>;
  },
}));

beforeEach(() => {
  state.broken = true;
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("one section throwing leaves the rest of Settings usable, and retries alone", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/tutor/settings"]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const broken = await screen.findByRole("region", { name: "AI marking agreement" });
  expect(within(broken).getByText("This section didn't load")).toBeInTheDocument();

  for (const heading of [
    "Teaching guidance",
    "Grade boundaries",
    "Mistake categories",
    "Preferences",
    "Account and integrations",
  ]) {
    expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
  }
  expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();

  state.broken = false;
  fireEvent.click(within(broken).getByRole("button", { name: /Try again/ }));
  expect(await screen.findByText("Marking rules recovered")).toBeInTheDocument();
});
