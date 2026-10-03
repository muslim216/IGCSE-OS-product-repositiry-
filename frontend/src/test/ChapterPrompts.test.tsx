import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import ChapterPrompts from "../tutor/today/ChapterPrompts";
import type { ChapterPrompt } from "../api/today";

const base: ChapterPrompt = {
  group_id: 3,
  group_name: "Year 11 Chemistry",
  subject_name: "Chemistry",
  chapter_id: 9,
  chapter_code: "4",
  chapter_title: "Organic chemistry",
  starts_on: "2026-10-01",
  ends_on: "2026-10-20",
  started: true,
};

function renderPrompts(prompts: ChapterPrompt[]) {
  return render(
    <MemoryRouter>
      <ChapterPrompts prompts={prompts} />
    </MemoryRouter>,
  );
}

test("a started chapter names the class, the chapter and links to the upload", () => {
  renderPrompts([base]);
  expect(screen.getByText("Coming up in your plan")).toBeInTheDocument();
  expect(screen.getByText(/Year 11 Chemistry/)).toBeInTheDocument();
  expect(screen.getByText(/Chapter 4 · Organic chemistry/)).toBeInTheDocument();
  expect(screen.getByText(/no classified uploaded yet/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Upload a classified/ })).toHaveAttribute(
    "href",
    "/tutor/groups/3/new-homework",
  );
});

test("a chapter still ahead says when it starts", () => {
  renderPrompts([{ ...base, started: false, starts_on: "2026-10-09" }]);
  expect(screen.getByText(/starts .*9/)).toBeInTheDocument();
});

test("one row per prompt", () => {
  renderPrompts([base, { ...base, group_id: 4, group_name: "Year 10", chapter_id: 10 }]);
  expect(screen.getAllByRole("link", { name: /Upload a classified/ })).toHaveLength(2);
});

test("no prompts renders nothing at all", () => {
  const { container } = renderPrompts([]);
  expect(container).toBeEmptyDOMElement();
});
