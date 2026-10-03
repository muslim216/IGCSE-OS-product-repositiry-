import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import BehindClasses from "../tutor/today/BehindClasses";
import type { BehindClass } from "../api/today";

const base: BehindClass = {
  group_id: 3,
  group_name: "Year 11 Chemistry",
  missed: 3,
  earliest_missed_date: "2026-10-06",
  chapter_id: 9,
  chapter_code: "4",
  chapter_title: "Organic chemistry",
};

function renderList(classes: BehindClass[]) {
  return render(
    <MemoryRouter>
      <BehindClasses classes={classes} />
    </MemoryRouter>,
  );
}

test("names the class, the count, the first date and links to its plan, without blame", () => {
  const { container } = renderList([base]);
  expect(screen.getByText(/Year 11 Chemistry/)).toBeInTheDocument();
  expect(
    screen.getByText(/3 planned lessons haven't been recorded since Tue 6 Oct/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Chapter 4 · Organic chemistry/)).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/missed|behind|late/i);
  expect(
    screen.getByRole("link", { name: "Review the plan for Year 11 Chemistry" }),
  ).toHaveAttribute("href", "/tutor/groups/3/schedule");
});

test("one lesson is singular and every class gets a row", () => {
  renderList([
    { ...base, missed: 1 },
    { ...base, group_id: 4, group_name: "Year 10" },
  ]);
  expect(screen.getByText(/1 planned lesson hasn't been recorded/)).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /Review the plan/ })).toHaveLength(2);
});

test("nothing behind renders nothing at all", () => {
  const { container } = renderList([]);
  expect(container).toBeEmptyDOMElement();
});
