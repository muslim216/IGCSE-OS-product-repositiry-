import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import StudentContacts from "../tutor/StudentContacts";
import MessagesSetting from "../tutor/MessagesSetting";
import WeeklySendSetting from "../tutor/WeeklySendSetting";
import NotificationPreferences from "../components/NotificationPreferences";

/* Task 8.1's screens: an address is entered, shown back and confirmed before
   anything is sent to it (threat review F5); a reader chooses what reaches them
   per channel; and the tutor is told plainly when nothing can be sent yet. */

const role = vi.hoisted(() => ({ current: "tutor" }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: 1, name: "T", role: role.current } }),
}));

type Call = { method: string; path: string; body?: Record<string, unknown> };

function contact(over: object = {}) {
  return {
    id: 9,
    channel: "whatsapp",
    address: "+201001234567",
    confirmed_at: null,
    confirmed_by_id: null,
    suppressed_at: null,
    suppressed_reason: null,
    ...over,
  };
}

function stub(routes: Record<string, (call: Call) => unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname.replace("/api/v1", "");
      const method = (init?.method ?? "GET").toUpperCase();
      const call = { method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const handler = routes[`${method} ${path}`];
      if (!handler) return new Response("[]", { status: 200 });
      const result = handler(call);
      if (typeof result === "number") {
        return new Response(JSON.stringify({ detail: "Enter the number properly" }), {
          status: result,
        });
      }
      return new Response(JSON.stringify(result), { status: 200 });
    }),
  );
  return calls;
}

function mount(ui: ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {ui}
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  role.current = "tutor";
});

// ---------------------------------------------------------------- contacts

test("a saved number is shown back and only confirmed by an explicit press", async () => {
  let saved: object | undefined;
  const calls = stub({
    "GET /students/4/contacts": () => [
      { user_id: 4, name: "Sara", role: "student", contacts: saved ? [saved] : [] },
    ],
    "PUT /students/4/contacts": (call) => (saved = contact({ address: call.body!.address })),
    "POST /students/4/contacts/9/confirm": () =>
      (saved = contact({ confirmed_at: "2026-10-05T10:00:00Z" })),
  });
  mount(<StudentContacts studentId={4} />);
  const field = await screen.findByLabelText("WhatsApp for Sara");
  fireEvent.change(field, { target: { value: "+201001234567" } });
  fireEvent.submit(field.closest("form")!);

  const check = await screen.findByRole("group", { name: "Confirm WhatsApp for Sara" });
  expect(check).toHaveTextContent("+201001234567");
  expect(check).toHaveTextContent("Nothing is sent here until you confirm it.");
  // Saving sent no confirmation of its own.
  expect(calls.some((c) => c.path.endsWith("/confirm"))).toBe(false);
  // The learner's own number carries no user_id; a parent's would.
  expect(calls.find((c) => c.method === "PUT")!.body).toEqual({
    channel: "whatsapp",
    address: "+201001234567",
  });

  fireEvent.click(within(check).getByRole("button", { name: "This is right" }));
  expect(await screen.findByText(/Confirmed — messages go to/)).toBeInTheDocument();
});

test("a parent's number is saved against the parent, and an opt-out is said plainly", async () => {
  const calls = stub({
    "GET /students/4/contacts": () => [
      { user_id: 4, name: "Sara", role: "student", contacts: [] },
      {
        user_id: 8,
        name: "Mona",
        role: "parent",
        contacts: [
          contact({ suppressed_at: "2026-10-01T00:00:00Z", suppressed_reason: "opted_out" }),
        ],
      },
    ],
    "PUT /students/4/contacts": () => contact(),
  });
  mount(<StudentContacts studentId={4} />);
  expect(await screen.findByText(/Opted out — they asked us to stop/)).toBeInTheDocument();
  const email = screen.getByLabelText("Email for Mona");
  fireEvent.change(email, { target: { value: "mona@example.com" } });
  fireEvent.submit(email.closest("form")!);
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      channel: "email",
      address: "mona@example.com",
      user_id: 8,
    }),
  );
  // With a parent present, the "no parent yet" hint is not shown.
  expect(screen.queryByText(/No parent has joined yet/)).not.toBeInTheDocument();
});

test("a refused number shows the server's reason and nothing is confirmed", async () => {
  stub({
    "GET /students/4/contacts": () => [{ user_id: 4, name: "Sara", role: "student", contacts: [] }],
    "PUT /students/4/contacts": () => 422,
  });
  mount(<StudentContacts studentId={4} />);
  const field = await screen.findByLabelText("WhatsApp for Sara");
  fireEvent.change(field, { target: { value: "01001234567" } });
  fireEvent.submit(field.closest("form")!);
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter the number properly");
  expect(screen.queryByRole("group", { name: /Confirm/ })).not.toBeInTheDocument();
  expect(screen.getByText(/No parent has joined yet/)).toBeInTheDocument();
});

// ----------------------------------------------------------------- settings

test("the tutor is told when WhatsApp isn't connected, and what happens meanwhile", async () => {
  stub({
    "GET /notifications/status": () => ({ whatsapp_configured: false, email_configured: false }),
    "GET /notifications/undelivered": () => [
      {
        id: 1,
        recipient_user_id: 8,
        recipient_name: "Mona",
        recipient_role: "parent",
        kind: "weekly_send",
        status: "no_channel",
        reason: "No confirmed contact for this person",
        created_at: "2026-10-04T17:00:00Z",
      },
    ],
  });
  mount(<MessagesSetting />);
  expect(await screen.findByRole("status")).toHaveTextContent("messages are recorded but not sent");
  const failed = (await screen.findByText("Mona")).closest("li")!;
  expect(failed).toHaveTextContent("The weekly summary");
  expect(failed).toHaveTextContent("No confirmed number or email");
});

test("with WhatsApp connected and nothing undelivered, neither notice appears", async () => {
  const calls = stub({
    "GET /notifications/status": () => ({ whatsapp_configured: true, email_configured: false }),
  });
  mount(<MessagesSetting />);
  await screen.findByLabelText("WhatsApp for you");
  await waitFor(() =>
    expect(calls.some((c) => c.path === "/notifications/undelivered")).toBe(true),
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByText(/didn't reach anyone/)).not.toBeInTheDocument();
});

test("the weekly summary's day, time and language each save on their own", async () => {
  const org = { weekly_send_weekday: 6, weekly_send_hour: 17, ai_language: "en", timezone: null };
  const calls = stub({
    "GET /me/organization": () => org,
    "PUT /me/organization": (call) => ({ ...org, ...call.body }),
  });
  mount(<WeeklySendSetting />);
  const day = await screen.findByLabelText("Day");
  expect(day).toHaveValue("6");
  expect(screen.getByLabelText("Time")).toHaveValue("17");
  fireEvent.change(day, { target: { value: "4" } });
  await waitFor(() => expect(screen.getByLabelText("Day")).toHaveValue("4"));
  fireEvent.change(screen.getByLabelText("Written in"), { target: { value: "ar" } });
  await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
  expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([
    { weekly_send_weekday: 4 },
    { ai_language: "ar" },
  ]);
});

// -------------------------------------------------------------- preferences

test("a reader is offered only the messages their role is sent, on by default", async () => {
  role.current = "parent";
  const calls = stub({
    "GET /me/notification-preferences": () => [
      { kind: "homework_set", channel: "email", enabled: false },
    ],
    "PUT /me/notification-preferences": (call) => call.body!.preferences,
  });
  mount(<NotificationPreferences />);
  const weekly = await screen.findByLabelText("The weekly summary by WhatsApp");
  expect(weekly).toBeChecked();
  expect(screen.getByLabelText("New homework by Email")).not.toBeChecked();
  // A parent is never sent lesson reminders or the tutor's review nudge.
  expect(screen.queryByLabelText(/Lesson reminders/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/waiting for review/)).not.toBeInTheDocument();

  fireEvent.click(weekly);
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      preferences: [{ kind: "weekly_send", channel: "whatsapp", enabled: false }],
    }),
  );
});
