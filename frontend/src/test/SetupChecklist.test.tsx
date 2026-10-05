import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import SetupChecklist from "../tutor/today/SetupChecklist";

/* The setup card on the tutor's home (9.1d). The server says what is done; these
   tests give it payloads and check what is shown and what is posted. */

const item = (key: string, state: string, kind = "defaulted") => ({ key, kind, state });
const allDone = [
  { key: "timetable", done: true },
  { key: "taught_before", done: true },
  { key: "plan_inputs", done: true },
  { key: "plan_accepted", done: true },
];

function subject(over: Record<string, unknown> = {}) {
  return {
    subject_id: 7,
    subject_name: "Chemistry",
    required: [{ key: "syllabus", done: true }],
    items: [
      item("boundaries", "set_by_you"),
      item("marking_rules", "set_by_you"),
      item("mistake_categories", "set_by_you"),
      item("weak_threshold", "set_by_you"),
      item("teaching_guidance", "set_by_you", "optional"),
    ],
    reviewed_count: 4,
    review_total: 4,
    // A subject with no class is itself outstanding, so a finished one has a class.
    classes: [{ group_id: 1, group_name: "Chem A", steps: allDone, complete: true }],
    ...over,
  };
}

function state(over: Record<string, unknown> = {}) {
  return {
    complete: false,
    in_flow: false,
    account: item("account_basics", "set_by_you"),
    subjects: [subject()],
    next_step: null,
    ...over,
  };
}

let payload: unknown;
let failLoad = false;
let failAck = false;
let acks: unknown[] = [];
let ackResponse: unknown;
let client: QueryClient;

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (path === "/api/v1/onboarding/acknowledgements") {
        acks.push(JSON.parse(String(init?.body)));
        if (failAck) return new Response(JSON.stringify({ detail: "Nope" }), { status: 500 });
        if (ackResponse !== undefined) return json(ackResponse);
        return json(
          state({
            account: item("account_basics", "reviewed"),
            subjects: [
              subject({
                items: [
                  item("boundaries", "set_by_you"),
                  item("marking_rules", "reviewed"),
                  item("mistake_categories", "set_by_you"),
                  item("weak_threshold", "set_by_you"),
                  item("teaching_guidance", "set_by_you", "optional"),
                ],
                reviewed_count: 4,
              }),
            ],
          }),
        );
      }
      if (path === "/api/v1/onboarding") {
        if (failLoad) return new Response("{}", { status: 500 });
        return json(payload);
      }
      return json([]);
    }),
  );
}

function renderCard() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SetupChecklist />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  payload = state();
  failLoad = false;
  failAck = false;
  acks = [];
  ackResponse = undefined;
  stub();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("nothing outstanding: no card at all", async () => {
  const { container } = renderCard();
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 20));
  expect(container).toBeEmptyDOMElement();
});

test("optional teaching guidance alone never keeps the card alive", async () => {
  payload = state({
    subjects: [
      subject({
        items: [
          item("boundaries", "set_by_you"),
          item("marking_rules", "set_by_you"),
          item("mistake_categories", "set_by_you"),
          item("weak_threshold", "set_by_you"),
          item("teaching_guidance", "not_set", "optional"),
        ],
      }),
    ],
  });
  const { container } = renderCard();
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 20));
  expect(container).toBeEmptyDOMElement();
});

test("each kind of row shows with its link, and the counts are the server's", async () => {
  payload = state({
    account: item("account_basics", "default"),
    subjects: [
      subject({
        required: [{ key: "syllabus", done: false }],
        items: [
          item("boundaries", "not_set"),
          item("marking_rules", "default"),
          item("mistake_categories", "reviewed"),
          item("weak_threshold", "default"),
          item("teaching_guidance", "not_set", "optional"),
        ],
        reviewed_count: 1,
        review_total: 4,
      }),
    ],
  });
  renderCard();
  const card = await screen.findByRole("region", { name: "Setup" });

  expect(within(card).getByText(/None of this blocks anything/)).toBeInTheDocument();
  expect(within(card).getByText(/Time zone, AI language and weekly send day/)).toBeInTheDocument();
  expect(within(card).getByRole("link", { name: /Review account settings/ })).toHaveAttribute(
    "href",
    "/tutor/settings",
  );

  const chemistry = within(card).getByRole("group", { name: /Chemistry/ });
  expect(within(chemistry).getByText("1 of 4 settings reviewed")).toBeInTheDocument();
  expect(within(chemistry).getByText("No syllabus yet")).toBeInTheDocument();
  expect(within(chemistry).getByRole("link", { name: /Add a syllabus/ })).toHaveAttribute(
    "href",
    "/tutor/subject-setup?subject=7#syllabus",
  );
  expect(
    within(chemistry).getByText(
      /No grade boundaries saved, so this subject has no predicted grades/,
    ),
  ).toBeInTheDocument();
  expect(within(chemistry).getByRole("link", { name: /Set boundaries/ })).toHaveAttribute(
    "href",
    "/tutor/subject-setup?subject=7#boundaries",
  );
  expect(within(chemistry).getByRole("link", { name: /Review Marking rules/ })).toHaveAttribute(
    "href",
    "/tutor/subject-setup?subject=7#marking-rules",
  );
  expect(
    within(chemistry).getByRole("link", { name: /Review Weak-topic threshold/ }),
  ).toHaveAttribute("href", "/tutor/subject-setup?subject=7#preferences");
  expect(within(chemistry).getByText("Teaching guidance (optional)")).toBeInTheDocument();
  expect(within(chemistry).getByRole("link", { name: /Add teaching guidance/ })).toHaveAttribute(
    "href",
    "/tutor/subject-setup?subject=7#teaching-guidance",
  );
  // Reviewed items are not listed again.
  expect(within(chemistry).queryByText(/Mistake categories/)).not.toBeInTheDocument();
  // Boundaries not_set has no default to keep.
  expect(
    screen.queryByRole("button", { name: /Keep the default for Grade boundaries/ }),
  ).not.toBeInTheDocument();
});

test("keeping a default posts that item and the row goes using the response", async () => {
  payload = state({
    subjects: [
      subject({
        items: [
          item("boundaries", "set_by_you"),
          item("marking_rules", "default"),
          item("mistake_categories", "set_by_you"),
          item("weak_threshold", "set_by_you"),
          item("teaching_guidance", "set_by_you", "optional"),
        ],
        reviewed_count: 3,
      }),
    ],
  });
  renderCard();
  const keep = await screen.findByRole("button", {
    name: "Keep the default for Marking rules, Chemistry",
  });
  fireEvent.click(keep);
  await waitFor(() => expect(acks).toEqual([{ item: "marking_rules", subject_id: 7 }]));
  // The response leaves nothing outstanding, so the card goes with the row.
  await waitFor(() => expect(screen.queryByRole("region", { name: "Setup" })).toBeNull());
});

test("keeping the account defaults posts account_basics with no subject", async () => {
  payload = state({ account: item("account_basics", "default") });
  renderCard();
  fireEvent.click(await screen.findByRole("button", { name: /Keep the defaults for account/ }));
  await waitFor(() => expect(acks).toEqual([{ item: "account_basics", subject_id: null }]));
});

test("a failed acknowledgement shows the error and keeps the row", async () => {
  failAck = true;
  payload = state({
    subjects: [
      subject({
        items: [
          item("boundaries", "set_by_you"),
          item("marking_rules", "default"),
          item("mistake_categories", "set_by_you"),
          item("weak_threshold", "set_by_you"),
          item("teaching_guidance", "set_by_you", "optional"),
        ],
      }),
    ],
  });
  renderCard();
  fireEvent.click(
    await screen.findByRole("button", { name: /Keep the default for Marking rules/ }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(/went wrong/i);
  expect(screen.getByRole("button", { name: /Keep the default for Marking rules/ })).toBeEnabled();
});

test("a class shows only its first undone step, linked to where it is done", async () => {
  const steps = (done: boolean[]) => allDone.map((s, i) => ({ key: s.key, done: done[i] }));
  payload = state({
    subjects: [
      subject({
        classes: [
          {
            group_id: 11,
            group_name: "Chem A",
            steps: steps([false, false, false, false]),
            complete: false,
          },
          {
            group_id: 12,
            group_name: "Chem B",
            steps: steps([true, false, false, false]),
            complete: false,
          },
          {
            group_id: 13,
            group_name: "Chem C",
            steps: steps([true, true, false, false]),
            complete: false,
          },
          {
            group_id: 14,
            group_name: "Chem D",
            steps: steps([true, true, true, false]),
            complete: false,
          },
          {
            group_id: 15,
            group_name: "Chem E",
            steps: steps([true, true, true, true]),
            complete: true,
          },
        ],
      }),
    ],
  });
  renderCard();
  const card = await screen.findByRole("region", { name: "Setup" });
  const link = (name: RegExp) => within(card).getByRole("link", { name });
  expect(link(/Add a timetable for Chem A/)).toHaveAttribute("href", "/tutor/groups/11/schedule");
  expect(link(/Say where this class is up to for Chem B/)).toHaveAttribute(
    "href",
    "/tutor/groups/12/syllabus#taught-before",
  );
  expect(link(/Enter the plan details for Chem C/)).toHaveAttribute(
    "href",
    "/tutor/groups/13/schedule",
  );
  expect(link(/Accept the teaching plan for Chem D/)).toHaveAttribute(
    "href",
    "/tutor/groups/14/schedule",
  );
  // One step per class, and a finished class is not listed.
  expect(within(card).getAllByRole("link")).toHaveLength(4);
  expect(within(card).queryByText("Chem E")).not.toBeInTheDocument();
});

test("a failed load says so once and offers a retry", async () => {
  failLoad = true;
  renderCard();
  expect(await screen.findByText(/Setup checklist couldn't be loaded/)).toBeInTheDocument();
  failLoad = false;
  payload = state({ account: item("account_basics", "default") });
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("region", { name: "Setup" })).toBeInTheDocument();
});

/* On the real page: the card is on the dashboard, not in the setup flow. */
function renderApp() {
  localStorage.setItem("avora-tokens", JSON.stringify({ access_token: "t", token_type: "bearer" }));
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={["/tutor"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function stubApp(classCount: number, onboarding: "fail" | "bad" | "default") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/auth/me"))
        return json({ id: 1, email: "t@example.com", username: null, role: "tutor", name: "T" });
      if (url.includes("/api/v1/onboarding")) {
        if (onboarding === "fail") return new Response("{}", { status: 500 });
        if (onboarding === "bad") return json([]);
        // An account with no class is in the setup flow; the server says so.
        return json(
          classCount === 0
            ? state({
                in_flow: true,
                subjects: [],
                next_step: { key: "syllabus", subject_id: null, group_id: null },
              })
            : state({ account: item("account_basics", "default") }),
        );
      }
      if (url.includes("/api/v1/today/overview")) return new Response("{}", { status: 500 });
      if (url.includes("/api/v1/today"))
        return json({
          classes: [],
          lessons: [],
          review_count: 0,
          class_count: classCount,
          joined_student_count: 0,
          classes_with_evidence: 0,
        });
      return json([]);
    }),
  );
}

test("the dashboard shows the card, and the setup flow does not", async () => {
  stubApp(1, "default");
  const { unmount } = renderApp();
  expect(await screen.findByRole("region", { name: "Setup" })).toBeInTheDocument();
  unmount();

  stubApp(0, "default");
  renderApp();
  expect(
    await screen.findByRole("heading", { level: 1, name: "Set up your first class" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Setup" })).not.toBeInTheDocument();
});

test("a failed or malformed onboarding read does not take the dashboard down", async () => {
  stubApp(1, "fail");
  const { unmount } = renderApp();
  expect(await screen.findByText(/Setup checklist couldn't be loaded/)).toBeInTheDocument();
  unmount();

  stubApp(1, "bad");
  renderApp();
  expect(await screen.findByText(/Setup checklist couldn't be loaded/)).toBeInTheDocument();
});

test("the dashboard's status region announces a save", async () => {
  stubApp(1, "default");
  renderApp();
  fireEvent.click(await screen.findByRole("button", { name: /Keep the defaults for account/ }));
  await waitFor(() => expect(screen.getByText(/^Saved\. Setup updated\./)).toBeInTheDocument());
});

test("a subject with a syllabus and no class keeps the card, with a row to add one", async () => {
  payload = state({ subjects: [subject({ classes: [] })] });
  renderCard();
  const card = await screen.findByRole("region", { name: "Setup" });
  expect(within(card).getByText("No class yet for this subject")).toBeInTheDocument();
  expect(within(card).getByRole("link", { name: /Add a class for Chemistry/ })).toHaveAttribute(
    "href",
    "/tutor/classes",
  );
});

test("a class step the client does not know is still outstanding", async () => {
  payload = state({
    subjects: [
      subject({
        classes: [
          {
            group_id: 21,
            group_name: "Chem Z",
            steps: [{ key: "something_new", done: false }],
            complete: false,
          },
        ],
      }),
    ],
  });
  renderCard();
  const link = await screen.findByRole("link", { name: /Finish setting up this class/ });
  expect(link).toHaveAttribute("href", "/tutor/groups/21");
});

test("a failed background refetch keeps the card that is already there", async () => {
  payload = state({ account: item("account_basics", "default") });
  renderCard();
  await screen.findByRole("region", { name: "Setup" });
  failLoad = true;
  await client.invalidateQueries({ queryKey: ["onboarding"] });
  await waitFor(() => expect(client.getQueryState(["onboarding"])?.status).toBe("error"));
  expect(screen.getByRole("region", { name: "Setup" })).toBeInTheDocument();
  expect(screen.queryByText(/couldn't be loaded/)).not.toBeInTheDocument();
});

test("a payload with a subject's items missing is a failed load, not a crash", async () => {
  payload = state({ subjects: [{ subject_id: 7, subject_name: "Chemistry" }] });
  renderCard();
  expect(await screen.findByText(/Setup checklist couldn't be loaded/)).toBeInTheDocument();
});

test("after an acknowledge that leaves the card standing, focus lands on its heading", async () => {
  const withItems = (marking: string) =>
    state({
      subjects: [
        subject({
          items: [
            item("boundaries", "set_by_you"),
            item("marking_rules", marking),
            item("mistake_categories", "default"),
            item("weak_threshold", "set_by_you"),
            item("teaching_guidance", "set_by_you", "optional"),
          ],
        }),
      ],
    });
  payload = withItems("default");
  ackResponse = withItems("reviewed");
  renderCard();
  fireEvent.click(
    await screen.findByRole("button", { name: /Keep the default for Marking rules/ }),
  );
  await waitFor(() => expect(screen.getByRole("heading", { name: "Setup" })).toHaveFocus());
});

test("when the last thing is cleared, focus moves to a note where the card was", async () => {
  payload = state({
    subjects: [
      subject({
        items: [
          item("boundaries", "set_by_you"),
          item("marking_rules", "default"),
          item("mistake_categories", "set_by_you"),
          item("weak_threshold", "set_by_you"),
          item("teaching_guidance", "set_by_you", "optional"),
        ],
      }),
    ],
  });
  renderCard();
  fireEvent.click(
    await screen.findByRole("button", { name: /Keep the default for Marking rules/ }),
  );
  const note = await screen.findByText("Nothing is left in the setup checklist.");
  await waitFor(() => expect(note).toHaveFocus());
});
