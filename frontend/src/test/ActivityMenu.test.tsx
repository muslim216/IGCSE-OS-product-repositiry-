import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import ActivityMenu from "../components/ActivityMenu";

const SUMMARY = {
  count: 1,
  items: [
    {
      kind: "homework_marked",
      label: "Algebra homework marked",
      sublabel: "Maths",
      link: "/student/homework/3",
      occurred_at: "2026-09-30T10:00:00Z",
    },
  ],
};

const ok = () => new Response(JSON.stringify(SUMMARY), { status: 200 });
const failure = () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 });

/** Each call takes the next response; the last one repeats. */
function stubFetch(...responses: (() => Response)[]) {
  const fetchMock = vi.fn(async () => (responses.length > 1 ? responses.shift()! : responses[0])());
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderMenu() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        {/* Stands in for the desktop sidebar: its own scroll container. */}
        <aside data-testid="sidebar" style={{ overflowY: "auto" }}>
          <ActivityMenu />
        </aside>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a failed load offers a retry rather than waiting out the poll", async () => {
  const fetchMock = stubFetch(failure, ok);
  renderMenu();
  fireEvent.click(screen.getByRole("button", { name: "Activity" }));
  expect(await screen.findByText("Activity couldn't be loaded.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Algebra homework marked")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("the bell discloses the panel it controls, and does not announce a menu", async () => {
  stubFetch(ok);
  renderMenu();
  const bell = await screen.findByRole("button", { name: "Activity, 1 waiting" });
  expect(bell).not.toHaveAttribute("aria-haspopup");
  expect(bell).not.toHaveAttribute("aria-controls");

  fireEvent.click(bell);
  expect(bell).toHaveAttribute("aria-expanded", "true");
  const panel = document.getElementById(bell.getAttribute("aria-controls")!);
  expect(panel).toHaveTextContent("Algebra homework marked");
});

test("scrolling what the bell sits in closes the panel; scrolling the panel does not", async () => {
  // The panel is fixed-position, placed from where the bell was on open. When
  // the sidebar scrolls, the bell moves and the panel would be left behind.
  stubFetch(ok);
  renderMenu();
  fireEvent.click(await screen.findByRole("button", { name: "Activity, 1 waiting" }));
  expect(await screen.findByText("Algebra homework marked")).toBeInTheDocument();

  fireEvent.scroll(screen.getByRole("list"));
  // A page scroll leaves the sticky bell where it was — and it is what an
  // over-scroll of the panel's own list turns into.
  fireEvent.scroll(document);
  expect(screen.getByText("Algebra homework marked")).toBeInTheDocument();

  fireEvent.scroll(screen.getByTestId("sidebar"));
  await waitFor(() =>
    expect(screen.queryByText("Algebra homework marked")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "Activity, 1 waiting" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});
