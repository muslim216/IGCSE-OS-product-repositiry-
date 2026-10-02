import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { Modal, Reveal, useToast } from "../components/ui";
import { EXIT_MS } from "../lib/motion";

/* Things that animate out are kept in the DOM for the length of the exit, and
   only on a device that has said motion is fine. jsdom has no matchMedia, so
   every other test in the suite runs the reduced-motion path — removed at
   once — and these stub the answer to reach the other one. */

function allowMotion() {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: query.includes("no-preference"), media: query })),
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function Confirm({ target, onClose }: { target: string | null; onClose: () => void }) {
  return (
    <Modal open={target !== null} onClose={onClose} title={`Remove ${target}?`}>
      <p>{target} will be removed.</p>
    </Modal>
  );
}

test("with reduced motion a closed dialog is gone in the same render", () => {
  const { rerender } = render(<Confirm target="Paper 1" onClose={vi.fn()} />);
  expect(screen.getByRole("dialog")).toBeInTheDocument();

  rerender(<Confirm target={null} onClose={vi.fn()} />);

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a closing dialog keeps what it said until its exit ends, then leaves", () => {
  allowMotion();
  const { rerender } = render(<Confirm target="Paper 1" onClose={vi.fn()} />);

  // Closing clears the state the title and body were drawn from.
  rerender(<Confirm target={null} onClose={vi.fn()} />);

  expect(screen.getByRole("dialog").parentElement).toHaveAttribute("data-closing");
  expect(screen.getByText("Remove Paper 1?")).toBeInTheDocument();
  expect(screen.getByText("Paper 1 will be removed.")).toBeInTheDocument();
  expect(screen.queryByText(/null/)).not.toBeInTheDocument();

  act(() => void vi.advanceTimersByTime(EXIT_MS));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("Escape during the exit does not close a second time", () => {
  allowMotion();
  const onClose = vi.fn();
  const { rerender } = render(<Confirm target="Paper 1" onClose={onClose} />);
  rerender(<Confirm target={null} onClose={onClose} />);

  fireEvent.keyDown(document, { key: "Escape" });

  expect(onClose).not.toHaveBeenCalled();
});

test("a dialog reopened mid-exit stays, with its new contents", () => {
  allowMotion();
  const { rerender } = render(<Confirm target="Paper 1" onClose={vi.fn()} />);
  rerender(<Confirm target={null} onClose={vi.fn()} />);
  rerender(<Confirm target="Paper 2" onClose={vi.fn()} />);

  act(() => void vi.advanceTimersByTime(EXIT_MS * 2));

  expect(screen.getByRole("dialog").parentElement).not.toHaveAttribute("data-closing");
  expect(screen.getByText("Remove Paper 2?")).toBeInTheDocument();
});

function Toaster() {
  const { toast, showToast } = useToast();
  return (
    <>
      <button onClick={() => showToast("Saved.")}>Save</button>
      {toast}
    </>
  );
}

test("a toast keeps its words while it leaves", () => {
  allowMotion();
  render(<Toaster />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Saved.")).not.toHaveAttribute("data-closing");

  act(() => void vi.advanceTimersByTime(3500));
  expect(screen.getByText("Saved.")).toHaveAttribute("data-closing");

  act(() => void vi.advanceTimersByTime(EXIT_MS));
  expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
});

test("with reduced motion a toast leaves when its time is up, as before", () => {
  render(<Toaster />);
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Saved.")).toBeInTheDocument();

  act(() => void vi.advanceTimersByTime(3500));

  expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
});

test("a folded panel renders nothing, so what is inside it does not run", () => {
  render(
    <Reveal open={false}>
      <p>Questions</p>
    </Reveal>,
  );
  expect(screen.queryByText("Questions")).not.toBeInTheDocument();
});

test("a panel folding shut keeps its contents until the fold ends", () => {
  allowMotion();
  // The way pages use it: the contents are only built while open.
  const panel = (open: boolean) => <Reveal open={open}>{open && <p>Questions</p>}</Reveal>;
  const { rerender, container } = render(panel(true));

  rerender(panel(false));
  expect(screen.getByText("Questions")).toBeInTheDocument();
  expect(container.querySelector(".avora-reveal")).toHaveAttribute("data-closing");

  act(() => void vi.advanceTimersByTime(EXIT_MS));
  expect(screen.queryByText("Questions")).not.toBeInTheDocument();
});

test("a closing dialog cannot be operated: it is inert for the length of the exit", () => {
  allowMotion();
  const { rerender } = render(<Confirm target="Paper 1" onClose={vi.fn()} />);
  expect(screen.getByRole("dialog").parentElement).not.toHaveAttribute("inert");

  rerender(<Confirm target={null} onClose={vi.fn()} />);

  expect(screen.getByRole("dialog", { hidden: true }).parentElement).toHaveAttribute("inert");
});

test("the exit timer and the exit animation are the same length", () => {
  // usePresence removes the element after EXIT_MS; the CSS animates it out
  // over --dur-exit. Shorter in CSS and it sits invisible; longer and it is
  // cut off mid-fade.
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");
  expect(css).toMatch(new RegExp(`--dur-exit:\\s*${EXIT_MS}ms;`));
});
