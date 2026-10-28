import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { Modal, useToast } from "../components/ui";
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

test("focus returns to the opener even when a child autofocuses an input", () => {
  function AutoFocusHarness() {
    const [open, setOpen] = useState(false);
    return (
      <div>
        <button type="button" onClick={() => setOpen(true)}>
          Reset
        </button>
        <Modal open={open} onClose={() => setOpen(false)} title="Reset?">
          <input aria-label="Password" autoFocus />
        </Modal>
      </div>
    );
  }
  render(<AutoFocusHarness />);
  const opener = screen.getByRole("button", { name: "Reset" });
  opener.focus();
  fireEvent.click(opener);
  expect(screen.getByLabelText("Password")).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(opener).toHaveFocus();
});

test("a toast fired while a dialog is open is not inside an inert element", () => {
  function ToastHarness() {
    const { toast, showToast } = useToast();
    return (
      <div>
        {toast}
        <Modal open onClose={() => {}} title="Busy">
          <button type="button" onClick={() => showToast("Saved")}>
            Save
          </button>
        </Modal>
      </div>
    );
  }
  render(<ToastHarness />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  const toast = screen.getByText("Saved");
  expect(toast.closest("[inert]")).toBeNull();
});

test("with two dialogs open, Escape closes only the top and Tab stays in it", () => {
  const closeOuter = vi.fn();
  const closeInner = vi.fn();
  render(
    <div>
      <Modal open onClose={closeOuter} title="Outer">
        <button type="button">Outer one</button>
        <button type="button">Outer two</button>
      </Modal>
      <Modal open onClose={closeInner} title="Inner">
        <button type="button">Inner one</button>
        <button type="button">Inner two</button>
      </Modal>
    </div>,
  );
  const innerTwo = screen.getByRole("button", { name: "Inner two" });
  innerTwo.focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Inner one" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(closeInner).toHaveBeenCalledTimes(1);
  expect(closeOuter).not.toHaveBeenCalled();
});

test("Tab skips controls that are disabled, hidden or in a disabled fieldset", () => {
  render(
    <Modal open onClose={() => {}} title="Skips">
      <button type="button">Real first</button>
      <button type="button">Real last</button>
      <fieldset disabled>
        <input aria-label="Locked" />
      </fieldset>
      <div hidden>
        <button type="button">Hidden</button>
      </div>
    </Modal>,
  );
  screen.getByRole("button", { name: "Real last" }).focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Real first" })).toHaveFocus();
});

test("focus falls back to main when the opener is gone", () => {
  function GoneHarness() {
    const [open, setOpen] = useState(false);
    const [row, setRow] = useState(true);
    return (
      <div>
        <main id="main" tabIndex={-1} />
        {row && (
          <button type="button" onClick={() => setOpen(true)}>
            Delete row
          </button>
        )}
        <Modal
          open={open}
          onClose={() => {
            setRow(false);
            setOpen(false);
          }}
          title="Delete?"
        >
          <button type="button">Cancel</button>
        </Modal>
      </div>
    );
  }
  render(<GoneHarness />);
  const opener = screen.getByRole("button", { name: "Delete row" });
  opener.focus();
  fireEvent.click(opener);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.getByRole("main")).toHaveFocus();
});

test("ProtectedRoute loading status carries readable text", () => {
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
  expect(screen.getByRole("status")).toHaveTextContent("Loading");
});

test("a click that does not focus its button still returns focus to that button", () => {
  function Unfocused() {
    const [open, setOpen] = useState(false);
    return (
      <div>
        <input aria-label="Search" />
        <button type="button" onClick={() => setOpen(true)}>
          Open it
        </button>
        <Modal open={open} onClose={() => setOpen(false)} title="Hi">
          <button type="button">Inside</button>
        </Modal>
      </div>
    );
  }
  render(<Unfocused />);
  screen.getByLabelText("Search").focus();
  const trigger = screen.getByRole("button", { name: "Open it" });
  fireEvent.mouseDown(trigger);
  fireEvent.click(trigger);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(trigger).toHaveFocus();
});
