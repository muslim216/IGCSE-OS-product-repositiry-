import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ConfirmDialog, ErrorBoundary } from "../components/page";

function renderConfirm(busy: boolean) {
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Remove this lesson?"
      body="It disappears from the timetable."
      confirmLabel="Remove lesson"
      danger
      busy={busy}
      onConfirm={() => {}}
      onCancel={onCancel}
    />,
  );
  return onCancel;
}

test("a confirmation in flight cannot be dismissed as if it were cancelled", () => {
  // Escape and the backdrop used to call onCancel mid-request: the dialog
  // closed as though nothing would happen while the delete went through.
  const onCancel = renderConfirm(true);
  fireEvent.keyDown(document, { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(onCancel).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
});

test("an idle confirmation still closes on Escape and on the backdrop", () => {
  const onCancel = renderConfirm(false);
  fireEvent.keyDown(document, { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(onCancel).toHaveBeenCalledTimes(2);
});

describe("ErrorBoundary", () => {
  // React reports a caught render error to the console; that noise is the
  // expected behaviour under test, not a failure.
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  function Crash(): never {
    throw new Error("render failed");
  }
  const fallback = () => screen.queryByText("Something went wrong on this page");

  test("a new reset key clears a caught crash", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="a">
        <Crash />
      </ErrorBoundary>,
    );
    expect(fallback()).toBeInTheDocument();

    // The same navigation keeps the failure: nothing has changed to retry.
    rerender(
      <ErrorBoundary resetKey="a">
        <p>Page content</p>
      </ErrorBoundary>,
    );
    expect(fallback()).toBeInTheDocument();

    // Any navigation — even one that keeps the path — renders the page again.
    rerender(
      <ErrorBoundary resetKey="b">
        <p>Page content</p>
      </ErrorBoundary>,
    );
    expect(fallback()).not.toBeInTheDocument();
    expect(screen.getByText("Page content")).toBeInTheDocument();
  });

  test("a crash on the navigation that changed the key is still caught", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="a">
        <p>Page content</p>
      </ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary resetKey="b">
        <Crash />
      </ErrorBoundary>,
    );
    expect(fallback()).toBeInTheDocument();
  });
});
