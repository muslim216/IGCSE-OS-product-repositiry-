/**
 * frontend/src/api/narrative.ts — the two read-only wrappers the "Prepare
 * again" flow and the today/class-overview screens call to fetch a stored
 * narrative paragraph.
 *
 * These stub global fetch directly (the `client-errors.test.ts` convention)
 * rather than rendering the consuming components, since neither
 * TodayDashboard nor ClassOverview is part of this change.
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import type { Narrative } from "../api/narrative";
import { groupNarrative, studentNarrative } from "../api/narrative";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function stubFetchOnce(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("groupNarrative — the tutor_class audience", () => {
  test("requests the group's narrative by id", async () => {
    const fetchMock = stubFetchOnce({
      text: "The class is on track.",
      generated_at: "2026-01-01T00:00:00+00:00",
      prompt_version: "v1",
    });

    await groupNarrative(42);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/groups/42/narrative");
  });

  test("passes a stored narrative through unchanged", async () => {
    stubFetchOnce({
      text: "The class is on track.",
      generated_at: "2026-01-01T00:00:00+00:00",
      prompt_version: "v1",
    });

    const result = await groupNarrative(1);

    expect(result).toEqual<Narrative>({
      text: "The class is on track.",
      generated_at: "2026-01-01T00:00:00+00:00",
      prompt_version: "v1",
    });
  });

  test("a group with no narrative yet reports null fields, not empty strings", async () => {
    // PROD-2/UX-19: absence must be `null`, never a fabricated "" that would
    // render as a blank paragraph instead of an empty-state message.
    stubFetchOnce({ text: null, generated_at: null, prompt_version: null });

    const result = await groupNarrative(1);

    expect(result.text).toBeNull();
    expect(result.generated_at).toBeNull();
    expect(result.prompt_version).toBeNull();
  });
});

describe("studentNarrative — the parent_student audience", () => {
  test("requests the student's narrative by id, not the group's route", async () => {
    const fetchMock = stubFetchOnce({
      text: "Alex is making steady progress.",
      generated_at: "2026-01-02T00:00:00+00:00",
      prompt_version: "v1",
    });

    await studentNarrative(7);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/students/7/narrative");
  });

  test("a student with no narrative yet reports null fields, not empty strings", async () => {
    stubFetchOnce({ text: null, generated_at: null, prompt_version: null });

    const result = await studentNarrative(7);

    expect(result).toEqual<Narrative>({ text: null, generated_at: null, prompt_version: null });
  });
});

describe("auth wiring — inherited from api(), not reimplemented here", () => {
  test("an access token in storage is sent as a bearer header", async () => {
    localStorage.setItem(
      "igcse-os-tokens",
      JSON.stringify({ access_token: "test-token", token_type: "bearer" }),
    );
    const fetchMock = stubFetchOnce({ text: null, generated_at: null, prompt_version: null });

    await groupNarrative(1);

    const [, init] = fetchMock.mock.calls[0];
    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer test-token");
  });
});
