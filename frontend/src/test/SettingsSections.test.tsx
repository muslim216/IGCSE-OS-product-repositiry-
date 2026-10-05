import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import SettingsPage from "../tutor/SettingsPage";

// Messages stands in for any section that crashes while rendering. The same
// boundary around Subject setup's sections is pinned in SubjectSetup.test.tsx.
const state = vi.hoisted(() => ({ broken: true }));
vi.mock("../tutor/MessagesSetting", () => ({
  default: () => {
    if (state.broken) throw new Error("boom");
    return <p>Messages recovered</p>;
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

  const broken = await screen.findByRole("region", { name: "Messages" });
  expect(within(broken).getByText("This section didn't load")).toBeInTheDocument();

  expect(
    screen.getByRole("heading", { level: 2, name: "Account and integrations" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();

  state.broken = false;
  fireEvent.click(within(broken).getByRole("button", { name: /Try again/ }));
  expect(await screen.findByText("Messages recovered")).toBeInTheDocument();
});
