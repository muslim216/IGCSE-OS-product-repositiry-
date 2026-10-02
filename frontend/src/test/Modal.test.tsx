import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Modal } from "../components/ui";

/* Every ConfirmDialog caller hands Modal a fresh inline onClose on each render,
   and a background refetch re-renders the page under an open dialog. Focus has
   to stay where the user put it through that, and Escape has to call the
   onClose of the latest render, not the first. */

function Dialog({ onClose }: { onClose: () => void }) {
  return (
    <Modal open onClose={() => onClose()} title="Remove this resource?">
      <button type="button">Cancel</button>
      <button type="button">Remove</button>
    </Modal>
  );
}

test("a parent re-render does not pull focus off the dialog's buttons", () => {
  const { rerender } = render(<Dialog onClose={vi.fn()} />);
  const remove = screen.getByRole("button", { name: "Remove" });
  remove.focus();
  expect(remove).toHaveFocus();

  rerender(<Dialog onClose={vi.fn()} />);

  expect(remove).toHaveFocus();
});

test("Escape calls the latest onClose", () => {
  const first = vi.fn();
  const latest = vi.fn();
  const { rerender } = render(<Dialog onClose={first} />);
  rerender(<Dialog onClose={latest} />);

  fireEvent.keyDown(document, { key: "Escape" });

  expect(latest).toHaveBeenCalledTimes(1);
  expect(first).not.toHaveBeenCalled();
});
