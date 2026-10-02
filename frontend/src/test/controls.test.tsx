import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Field, Input, Select, Textarea } from "../components/controls";

/* The shared form controls. Their classes are the contract — Tailwind can only
   act on what reaches the class attribute — so these read the rendered class
   list rather than trusting the source. */

function classes(el: HTMLElement): string[] {
  return el.className.split(/\s+/).filter(Boolean);
}

test("a responsive width keeps the full-width default below its breakpoint", () => {
  // `sm:w-24` says nothing about small screens. Dropping `w-full` for it left
  // the field at its intrinsic width on a phone.
  render(<Input aria-label="Name" className="sm:w-24" />);
  const cls = classes(screen.getByLabelText("Name"));
  expect(cls).toContain("w-full");
  expect(cls).toContain("sm:w-24");
});

test("an unprefixed size replaces the default rather than fighting it", () => {
  render(<Select aria-label="Audience" className="h-8 w-auto" />);
  const cls = classes(screen.getByLabelText("Audience"));
  expect(cls).not.toContain("w-full");
  expect(cls).not.toContain("h-10");
  expect(cls).toEqual(expect.arrayContaining(["h-8", "w-auto"]));
});

test("a min-height is not mistaken for a height", () => {
  render(<Input aria-label="Code" className="min-h-12" />);
  expect(classes(screen.getByLabelText("Code"))).toContain("h-10");
  render(<Textarea aria-label="Notes" className="h-32" />);
  expect(classes(screen.getByLabelText("Notes"))).toContain("min-h-[5rem]");
});

test("the select's arrow is one class, not an SVG cut up at its spaces", () => {
  // The chevron used to be an inline data URL inside an arbitrary-value
  // utility. A class attribute splits on whitespace, so every space in the SVG
  // became a class boundary, Tailwind generated nothing, and no arrow drew.
  render(<Select aria-label="Subject" />);
  const cls = classes(screen.getByLabelText("Subject"));
  expect(cls).toContain("avora-select");
  expect(cls).toContain("appearance-none");
  for (const token of cls) {
    expect(token).not.toMatch(/svg|url\(|%22|[<>=]/);
  }
});

test("a field adds its hint to the control's own description", () => {
  render(
    <>
      <p id="extra">Shown on the report.</p>
      <Field label="Title" hint="Keep it short.">
        <Input aria-describedby="extra" />
      </Field>
    </>,
  );
  const input = screen.getByLabelText("Title");
  const ids = input.getAttribute("aria-describedby")!.split(" ");
  expect(ids[0]).toBe("extra");
  expect(ids).toHaveLength(2);
  expect(document.getElementById(ids[1])).toHaveTextContent("Keep it short.");
});

test("a field leaves the control's invalid state alone until it has an error", () => {
  const { rerender } = render(
    <Field label="Threshold">
      <Input aria-invalid />
    </Field>,
  );
  expect(screen.getByLabelText("Threshold")).toHaveAttribute("aria-invalid", "true");

  rerender(
    <Field label="Threshold" hint="0 to 100." error="Enter a number.">
      <Input />
    </Field>,
  );
  const input = screen.getByLabelText("Threshold");
  expect(input).toHaveAttribute("aria-invalid", "true");
  // The error replaces the hint on screen, so the hint is not referenced.
  const ids = input.getAttribute("aria-describedby")!.split(" ");
  expect(ids).toHaveLength(1);
  expect(document.getElementById(ids[0])).toHaveTextContent("Enter a number.");
});
