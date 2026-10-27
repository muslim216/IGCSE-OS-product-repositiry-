import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { Modal } from "../components/ui";
import AppShell from "../components/AppShell";
import { ProtectedRoute } from "../auth/ProtectedRoute";

const auth = vi.hoisted(() => ({ loading: false }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, name: "Demo", role: "tutor" },
    loading: auth.loading,
    signOut: vi.fn(),
  }),
}));
vi.mock("../components/ActivityMenu", () => ({ default: () => null }));

afterEach(() => {
  auth.loading = false;
});

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Sure?">
        <button type="button">First</button>
        <button type="button">Last</button>
      </Modal>
    </div>
  );
}

// jsdom does not move focus on Tab, so these drive the dialog's own key handler.
test("Tab wraps from last to first and Shift+Tab wraps back", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Open it" }));
  const first = screen.getByRole("button", { name: "First" });
  const last = screen.getByRole("button", { name: "Last" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(first).toHaveFocus();
});

test("closing returns focus to the opener", () => {
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "Open it" });
  opener.focus();
  fireEvent.click(opener);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(opener).toHaveFocus();
});

test("the page behind an open dialog is inert and the dialog is aria-modal", () => {
  const { container } = render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Open it" }));
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(container).toHaveAttribute("inert");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(container).not.toHaveAttribute("inert");
});

test("ProtectedRoute announces the session load", () => {
  auth.loading = true;
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<ProtectedRoute roles={["tutor"]} />}>
          <Route path="/" element={<p>in</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByRole("status")).toBeInTheDocument();
});

test("the skip link is the first tab stop and moves focus to main", () => {
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<AppShell title="Tutor" accountPath="/a" nav={[]} />}>
          <Route path="/" element={<p>page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  const skip = screen.getByRole("link", { name: "Skip to main content" });
  const firstStop = document.querySelector<HTMLElement>("a[href], button, [tabindex='0']");
  expect(firstStop).toBe(skip);
  fireEvent.click(skip);
  expect(screen.getByRole("main")).toHaveFocus();
});
