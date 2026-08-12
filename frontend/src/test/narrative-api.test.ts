/**
 * PR 15 — the thin client for the stored narrative (api/narrative.ts).
 *
 * There is no logic to speak of beyond the two paths, so what is worth
 * proving is that each function hits its own path (a class narrative must
 * never be requested at the student path or vice versa) and that an absent
 * narrative's null fields survive the round trip unchanged — never coerced
 * into an empty string that a surface would render as a blank panel
 * (PROD-2, UX-19).
 */
import { afterEach, expect, test, vi } from "vitest";
import { groupNarrative, studentNarrative } from "../api/narrative";

function stubFetch(body: unknown) {
  const mockFetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status: 200 }),
  );
  vi.stubGlobal("fetch", mockFetch);
  return mockFetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("groupNarrative reads the class paragraph at the group's own path", async () => {
  const mockFetch = stubFetch({
    text: "Bonding is the sticking point this week.",
    generated_at: "2026-01-01T00:00:00Z",
    prompt_version: "v1",
  });

  const result = await groupNarrative(5);

  expect(result.text).toBe("Bonding is the sticking point this week.");
  expect(result.generated_at).toBe("2026-01-01T00:00:00Z");
  expect(result.prompt_version).toBe("v1");
  const [url] = mockFetch.mock.calls[0];
  expect(String(url)).toContain("/api/v1/groups/5/narrative");
  expect(String(url)).not.toContain("/students/");
});

test("studentNarrative reads the parent paragraph at the student's own path", async () => {
  const mockFetch = stubFetch({
    text: "Sara is on track in Chemistry.",
    generated_at: "2026-01-02T00:00:00Z",
    prompt_version: "v1",
  });

  const result = await studentNarrative(9);

  expect(result.text).toBe("Sara is on track in Chemistry.");
  const [url] = mockFetch.mock.calls[0];
  expect(String(url)).toContain("/api/v1/students/9/narrative");
  expect(String(url)).not.toContain("/groups/");
});

test("different ids each hit their own path, not a shared or cached one", async () => {
  const mockFetch = stubFetch({ text: null, generated_at: null, prompt_version: null });

  await groupNarrative(1);
  await groupNarrative(2);

  const urls = mockFetch.mock.calls.map(([u]) => String(u));
  expect(urls[0]).toContain("/groups/1/narrative");
  expect(urls[1]).toContain("/groups/2/narrative");
});

test("an absent narrative's null fields pass through untouched, never coerced to ''", async () => {
  stubFetch({ text: null, generated_at: null, prompt_version: null });

  const result = await groupNarrative(5);

  expect(result.text).toBeNull();
  expect(result.generated_at).toBeNull();
  expect(result.prompt_version).toBeNull();
});