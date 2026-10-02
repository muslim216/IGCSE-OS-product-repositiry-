import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import PreferencesPage from "../tutor/PreferencesPage";

/* Readiness settings per scope (task 5.4a). "All subjects" is the account
   row; a subject either has its own override or shows the account's values,
   and saving on it creates the override. A switched-off factor is still
   computed, but never counts — the API refuses all six off, so the screen
   does too. */

const SUBJECTS = [
  { id: 7, exam_board: "Edexcel IGCSE", code: "4CH1", name: "Chemistry", grade_scale: "9-1" },
];

const FACTORS = [
  "topic_mastery",
  "past_paper_performance",
  "homework_performance",
  "assessment_performance",
  "syllabus_coverage",
  "mistake_analysis",
];

function config(subjectId: number | null, source: string, overrides: object = {}) {
  return {
    ...Object.fromEntries(FACTORS.map((f) => [`weight_${f}`, 1])),
    ...Object.fromEntries(FACTORS.map((f) => [`enabled_${f}`, true])),
    half_life_days: 45,
    weak_threshold: 60,
    subject_id: subjectId,
    source,
    ...overrides,
  };
}

function stub(subjectSource: "subject" | "account", { failSave = false, refuseSave = false } = {}) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  let source = subjectSource;
  let accountTopicMastery = 1;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: url.pathname + url.search, body });

      if (url.pathname === "/api/v1/subjects") return json(SUBJECTS);
      if (url.pathname === "/api/v1/readiness/weights") {
        const subject = url.searchParams.get("subject_id");
        const subjectId = subject === null ? null : Number(subject);
        if (method === "DELETE") {
          source = "account";
          return new Response(null, { status: 204 });
        }
        if (method === "PUT") {
          if (failSave) return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
          if (refuseSave)
            return new Response(
              JSON.stringify({
                detail: [{ loc: ["body"], msg: "Value error, switch on at least one factor" }],
              }),
              { status: 422 },
            );
          if (subjectId !== null) source = "subject";
          else accountTopicMastery = body.weight_topic_mastery;
          return json({
            ...body,
            subject_id: subjectId,
            source: subjectId ? "subject" : "account",
          });
        }
        const account = { weight_topic_mastery: accountTopicMastery };
        if (subjectId === null) return json(config(null, "account", account));
        return json(
          source === "subject"
            ? config(subjectId, "subject", { weight_topic_mastery: 2.5 })
            : config(subjectId, "account", account),
        );
      }
      return new Response(JSON.stringify({ detail: "unstubbed" }), { status: 404 });
    }),
  );
  return calls;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PreferencesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("switching a factor off saves it off, and all six off cannot be saved", async () => {
  const calls = stub("account");
  renderPage();

  const toggle = (await screen.findByRole("checkbox", {
    name: /counts towards readiness: mistake analysis/i,
  })) as HTMLInputElement;
  expect(toggle.checked).toBe(true);
  fireEvent.click(toggle);
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.url).toBe("/api/v1/readiness/weights");
  expect(put.body!.enabled_mistake_analysis).toBe(false);

  for (const box of screen.getAllByRole("checkbox") as HTMLInputElement[]) {
    if (box.checked) fireEvent.click(box);
  }
  await waitFor(() =>
    expect((screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement).disabled).toBe(
      true,
    ),
  );
  expect(screen.getByText(/at least one factor/i)).toBeTruthy();
});

test("saving a subject without an override creates one for that subject", async () => {
  const calls = stub("account");
  renderPage();

  await screen.findByRole("option", { name: /chemistry/i });
  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "7" },
  });
  expect(await screen.findByText(/using your account settings/i)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /remove override/i })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() =>
    expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("subject_id=7"))).toBe(true),
  );
});

test("a subject's override can be removed", async () => {
  const calls = stub("subject");
  renderPage();

  await screen.findByRole("option", { name: /chemistry/i });
  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "7" },
  });
  const remove = await screen.findByRole("button", { name: /remove override/i });
  const topicMastery = () =>
    (screen.getByRole("slider", { name: "Topic mastery" }) as HTMLInputElement).value;
  expect(topicMastery()).toBe("2.5");
  fireEvent.click(remove);

  await waitFor(() =>
    expect(
      calls.some(
        (c) => c.method === "DELETE" && c.url === "/api/v1/readiness/weights?subject_id=7",
      ),
    ).toBe(true),
  );
  // Falls back to the account settings once the override is gone.
  expect(await screen.findByText(/using your account settings/i)).toBeTruthy();
  // And the form shows the account's values, not the removed override's.
  await waitFor(() => expect(topicMastery()).toBe("1"));
});

test("a subject revisited after an account save shows the new account values", async () => {
  // The subject was cached before the save; its stale copy must not be what
  // the tutor edits, or saving it would write the old values as an override.
  const calls = stub("account");
  renderPage();
  const scope = async (value: string) => {
    await screen.findByRole("option", { name: /chemistry/i });
    fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
      target: { value },
    });
  };
  const topicMastery = async () =>
    ((await screen.findByRole("slider", { name: "Topic mastery" })) as HTMLInputElement).value;

  await scope("7");
  expect(await topicMastery()).toBe("1");
  await scope("");
  expect(await topicMastery()).toBe("1");
  fireEvent.change(screen.getByRole("slider", { name: "Topic mastery" }), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));

  await scope("7");
  await waitFor(async () => expect(await topicMastery()).toBe("2"));
});

test("a failed save's message does not follow the tutor to another scope", async () => {
  stub("account", { failSave: true });
  renderPage();
  await screen.findByRole("option", { name: /chemistry/i });
  fireEvent.click(await screen.findByRole("button", { name: /^save$/i }));
  expect(await screen.findByRole("alert")).toBeTruthy();

  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "7" },
  });
  await screen.findByText(/using your account settings/i);
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a subject inheriting the account can be customised, copying the account values", async () => {
  const calls = stub("account");
  renderPage();
  await screen.findByRole("option", { name: /chemistry/i });
  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "7" },
  });

  // An edit made before customising is what gets saved, not the inherited value.
  fireEvent.change(await screen.findByRole("slider", { name: "Topic mastery" }), {
    target: { value: "2" },
  });
  fireEvent.click(await screen.findByRole("button", { name: /customise for this subject/i }));

  await waitFor(() =>
    expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("subject_id=7"))).toBe(true),
  );
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.body!.weight_topic_mastery).toBe(2);
  expect(await screen.findByText(/this subject has its own settings/i)).toBeTruthy();
  expect(screen.getByRole("button", { name: /remove override/i })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /customise for this subject/i })).toBeNull();
});

test("the account scope offers no customise action", async () => {
  stub("account");
  renderPage();
  await screen.findByRole("slider", { name: "Topic mastery" });
  expect(screen.queryByRole("button", { name: /customise for this subject/i })).toBeNull();
});

test("an unsaved edit does not follow the tutor to another scope", async () => {
  stub("subject");
  renderPage();
  const topicMastery = async () =>
    ((await screen.findByRole("slider", { name: "Topic mastery" })) as HTMLInputElement).value;
  await screen.findByRole("option", { name: /chemistry/i });
  expect(await topicMastery()).toBe("1");
  fireEvent.change(screen.getByRole("slider", { name: "Topic mastery" }), {
    target: { value: "3" },
  });

  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "7" },
  });
  await waitFor(async () => expect(await topicMastery()).toBe("2.5"));

  fireEvent.change(screen.getByRole("combobox", { name: /settings for/i }), {
    target: { value: "" },
  });
  await waitFor(async () => expect(await topicMastery()).toBe("1"));
});

test("the server's refusal is shown in its own words", async () => {
  stub("account", { refuseSave: true });
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /^save$/i }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/at least one factor/i);
});

test("an edited weak threshold is what Save sends, and an empty one cannot be saved", async () => {
  const calls = stub("account");
  renderPage();
  const input = (await screen.findByRole("spinbutton", {
    name: /weak topic threshold/i,
  })) as HTMLInputElement;
  expect(input.value).toBe("60");

  fireEvent.change(input, { target: { value: "" } });
  const save = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
  await waitFor(() => expect(save.disabled).toBe(true));

  fireEvent.change(input, { target: { value: "45" } });
  await waitFor(() => expect(save.disabled).toBe(false));
  fireEvent.click(save);
  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  expect(calls.find((c) => c.method === "PUT")!.body!.weak_threshold).toBe(45);
});

test("a threshold-only save does not claim a recompute; a weight change does", async () => {
  stub("account");
  renderPage();
  const input = await screen.findByRole("spinbutton", { name: /weak topic threshold/i });
  fireEvent.change(input, { target: { value: "50" } });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  expect(await screen.findByText("Saved.")).toBeTruthy();
  expect(screen.queryByText(/recomputing/i)).toBeNull();

  fireEvent.change(screen.getByRole("slider", { name: /half-life/i }), {
    target: { value: "30" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
  expect(await screen.findByText(/recomputing readiness/i)).toBeTruthy();
});
