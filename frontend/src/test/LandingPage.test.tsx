import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

/* The public landing page's copy rules: the exact headline, the two entry
   points, the founder's note, no em-dashes, and a contact FAQ entry that only
   exists once there is a monitored inbox to send people to. */

const site = vi.hoisted(() => ({
  SITE: {
    name: "avora",
    legalName: "avora",
    contactEmail: null as string | null,
    privacyEmail: null as string | null,
    copyrightYear: 2026,
  },
}));
vi.mock("../lib/site", () => site);

import LandingPage from "../marketing/LandingPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  site.SITE.contactEmail = null;
});

test("the headline is the human one", () => {
  renderPage();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "Hand back marked homework without spending your evening on it.",
  );
});

test("the entry points: sign up, and a marked paper to look at", () => {
  const { container } = renderPage();
  const signups = screen.getAllByRole("link", { name: "Start free as a tutor" });
  expect(signups.length).toBeGreaterThanOrEqual(1);
  for (const a of signups) expect(a.getAttribute("href")).toBe("/signup");
  expect(screen.getByRole("link", { name: "See a marked paper" }).getAttribute("href")).toBe(
    "#marked-paper",
  );
  expect(container.querySelector("#marked-paper")).not.toBeNull();
});

test("the note from the builder is there, signed", () => {
  const { container } = renderPage();
  const note = container.querySelector("#note") as HTMLElement;
  expect(note).not.toBeNull();
  expect(within(note).getByText("A note from the person building avora")).toBeTruthy();
  expect(within(note).getByText("Building avora")).toBeTruthy();
  expect(within(note).getByText("What the pilot is")).toBeTruthy();
});

test("the page copy has no em-dashes", () => {
  renderPage();
  expect(screen.getByRole("main").textContent).not.toContain("—");
});

test("the contact FAQ entry appears only when a contact email is set", () => {
  const first = renderPage();
  expect(screen.queryByText("Can I talk to a person?")).toBeNull();
  // With no inbox, the page must not ask the reader to get in touch.
  expect(screen.getByRole("main").textContent).not.toMatch(/tell me|tell us|email /i);
  first.unmount();

  site.SITE.contactEmail = "hello@example.com";
  renderPage();
  expect(screen.getByText("Can I talk to a person?")).toBeTruthy();
  expect(screen.getByRole("main").textContent).toContain("email hello@example.com");
});

test("the page does not call the pilot closed while sign-up is open", () => {
  renderPage();
  expect(screen.getByRole("main").textContent).not.toMatch(
    /closed pilot|small (number|group) of tutors/i,
  );
});

test("the hero says what happens when there is no official mark scheme", () => {
  renderPage();
  expect(screen.getByRole("main").textContent).toMatch(
    /isn't sure of, or every mark when there's no official scheme/,
  );
});
