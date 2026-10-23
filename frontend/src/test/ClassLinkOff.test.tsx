import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import StudentsTab from "../tutor/tabs/StudentsTab";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const empty = () => new Response(null, { status: 204 });

afterEach(() => vi.unstubAllGlobals());

const SARA = { id: 42, name: "Sara", email: "sara@example.com", username: null, role: "student" };

/** The students tab for class 7, with `fetch` answered by `respond`. Returns the
 * list of "METHOD url" strings sent for anything other than a GET. */
function renderTab(respond: (url: string, init?: RequestInit) => Response, members: object[] = []) {
  const sent: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") sent.push(`${method} ${String(input)}`);
      return respond(String(input), init);
    }),
  );
  const group = { id: 7, name: "Y10", members, subject: { name: "Chemistry" } };
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={{ group, groupId: 7 }} />}>
            <Route index element={<StudentsTab />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return sent;
}

const LIVE = [{ code: "abc123", kind: "student_join", expires_at: null }];

test("a tutor switches the class link off after confirming, then sees no active link", async () => {
  let live = LIVE;
  const sent = renderTab((url, init) => {
    if (!url.endsWith("/groups/7/invites")) return json([]);
    if (init?.method !== "DELETE") return json(live);
    live = [];
    return empty();
  });

  fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
  // Nothing is revoked until the dialog is confirmed.
  expect(sent).toEqual([]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Switch off link" }));

  expect(await screen.findByText("No active link")).toBeInTheDocument();
  expect(sent).toEqual(["DELETE /api/v1/groups/7/invites"]);
  expect(screen.getByRole("status")).toHaveTextContent("Link switched off");
  expect(screen.getByRole("button", { name: /Make a new link/ })).toBeInTheDocument();
});

test("cancelling the switch-off sends nothing", async () => {
  const sent = renderTab((url) => (url.endsWith("/groups/7/invites") ? json(LIVE) : json([])));

  fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(sent).toEqual([]);
  expect(screen.getByRole("button", { name: "Switch off link" })).toBeInTheDocument();
});

test("a failed switch-off shows the error and keeps the link", async () => {
  renderTab((url, init) => {
    if (!url.endsWith("/groups/7/invites")) return json([]);
    if (init?.method === "DELETE") return json({ detail: "Group not found" }, 404);
    return json(LIVE);
  });

  fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Switch off link" }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("No active link")).not.toBeInTheDocument();
});

test("a removed student is listed and the tutor can add them back", async () => {
  let removed = [{ id: 42, name: "Sara", removed_at: "2026-10-20T10:00:00Z" }];
  const sent = renderTab((url, init) => {
    if (url.endsWith("/groups/7/removals")) return json(removed);
    if (url.endsWith("/groups/7/members") && init?.method === "POST") {
      expect(JSON.parse(String(init.body))).toEqual({ student_id: 42 });
      removed = [];
      return empty();
    }
    return json([]);
  });

  expect(await screen.findByText("Removed from this class")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add Sara back to this class" }));

  await waitFor(() =>
    expect(screen.queryByText("Removed from this class")).not.toBeInTheDocument(),
  );
  expect(sent).toEqual(["POST /api/v1/groups/7/members"]);
  expect(screen.getByRole("status")).toHaveTextContent("Sara added back");
  expect(screen.getByRole("heading", { name: "Students" })).toHaveFocus();
});

test("removing a student puts them in the removed list", async () => {
  let removed: object[] = [];
  const sent = renderTab(
    (url, init) => {
      if (url.endsWith("/groups/7/removals")) return json(removed);
      if (url.endsWith("/groups/7/members/42") && init?.method === "DELETE") {
        removed = [{ id: 42, name: "Sara", removed_at: "2026-10-20T10:00:00Z" }];
        return empty();
      }
      return json([]);
    },
    [SARA],
  );

  expect(screen.queryByText("Removed from this class")).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Remove Sara from this class" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Remove from class" }));

  expect(await screen.findByText("Removed from this class")).toBeInTheDocument();
  expect(sent).toEqual(["DELETE /api/v1/groups/7/members/42"]);
});

test("a failed load of the link or the removed list says so instead of showing nothing", async () => {
  renderTab(() => json({ detail: "boom" }, 500));

  const alerts = await screen.findAllByRole("alert");
  expect(alerts.map((a) => a.textContent).join(" ")).toMatch(/Couldn't load the invite link/);
  expect(alerts.map((a) => a.textContent).join(" ")).toMatch(/Couldn't load the students removed/);
});

test("switching off a second time changes the live region again so it is announced", async () => {
  let live: object[] = LIVE;
  renderTab((url, init) => {
    if (!url.endsWith("/groups/7/invites")) return json([]);
    if (init?.method === "DELETE") {
      live = [];
      return empty();
    }
    if (init?.method === "POST") {
      live = LIVE;
      return json(LIVE[0], 201);
    }
    return json(live);
  });

  const switchOffOnce = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Switch off link" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Switch off link" }));
    await screen.findByText("No active link");
    return screen.getByRole("status").textContent;
  };

  const first = await switchOffOnce();
  fireEvent.click(screen.getByRole("button", { name: /Make a new link/ }));
  await screen.findByRole("button", { name: "Switch off link" });
  const second = await switchOffOnce();

  expect(first).toContain("Link switched off");
  expect(second).toContain("Link switched off");
  expect(second).not.toBe(first);
});
