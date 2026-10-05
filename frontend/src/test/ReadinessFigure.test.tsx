import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import ReadinessFigure from "../components/ReadinessFigure";

function show(props: Parameters<typeof ReadinessFigure>[0]) {
  return render(
    <MemoryRouter>
      <ReadinessFigure {...props} />
    </MemoryRouter>,
  );
}

test("a full figure reads grade, status, percentage", () => {
  const { container } = show({ score: 64.4, grade: "6", status: "on_track" });
  expect(container.textContent).toContain("Grade 6");
  expect(container.textContent).toContain("On track");
  expect(container.textContent).toContain("64%");
  expect(screen.queryByText("Not enough data yet")).not.toBeInTheDocument();
});

test("no score, grade or status is stated as absent, never as 0%", () => {
  const { container } = show({ score: null, grade: null, status: null });
  expect(screen.getByText("Not enough data yet")).toBeInTheDocument();
  expect(container.textContent).not.toContain("0%");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test("a score with no boundaries has no grade and keeps the set-them hint", () => {
  const { container } = show({ score: 40, grade: null, status: null, boundariesMissing: true });
  expect(container.textContent).toContain("40%");
  expect(container.textContent).not.toContain("Grade");
  expect(screen.getByText(/no grade boundaries set/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Set them/ })).toHaveAttribute(
    "href",
    "/tutor/subject-setup#boundaries",
  );
});

test("no boundaries and no score still says there is not enough data", () => {
  show({ score: null, grade: null, status: null, boundariesMissing: true });
  expect(screen.getByText("Not enough data yet")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Set them/ })).toBeInTheDocument();
});

test("a grade without a score shows no percentage", () => {
  const { container } = show({ score: null, grade: "5", status: "at_risk" });
  expect(container.textContent).toContain("Grade 5");
  expect(container.textContent).toContain("At risk");
  expect(container.textContent).not.toContain("%");
});

test("a real score of zero is shown as 0%, because it is a measurement", () => {
  const { container } = show({ score: 0, grade: "1", status: "at_risk" });
  expect(container.textContent).toContain("0%");
});
