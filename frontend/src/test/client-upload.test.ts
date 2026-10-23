import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError, storeTokens, upload } from "../api/client";

class FakeXHR {
  static all: FakeXHR[] = [];
  upload: { onprogress: ((e: unknown) => void) | null; onload: (() => void) | null } = {
    onprogress: null,
    onload: null,
  };
  headers: Record<string, string> = {};
  status = 0;
  statusText = "";
  responseText = "";
  onload: (() => void | Promise<void>) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  withCredentials = false;
  constructor() {
    FakeXHR.all.push(this);
  }
  open() {}
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send() {}
  abort() {
    this.onabort?.();
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    return this.onload?.();
  }
}

const refreshOk = () =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ access_token: "new", token_type: "bearer" }))),
  );

beforeEach(() => {
  FakeXHR.all = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  localStorage.clear();
  storeTokens({ access_token: "old", token_type: "bearer" });
});
afterEach(() => vi.unstubAllGlobals());

test("sends the bearer token and reports progress", async () => {
  const seen: number[] = [];
  const p = upload("/x", new FormData(), { onProgress: (n) => seen.push(n) });
  const xhr = FakeXHR.all[0];
  expect(xhr.headers.Authorization).toBe("Bearer old");
  xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 });
  xhr.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
  await xhr.respond(200, { ok: 1 });
  await expect(p).resolves.toEqual({ ok: 1 });
  expect(seen).toEqual([25, 100]);
});

test("cancel aborts the request and rejects with AbortError", async () => {
  const ac = new AbortController();
  const p = upload("/x", new FormData(), { signal: ac.signal });
  ac.abort();
  await expect(p).rejects.toMatchObject({ name: "AbortError" });
});

test("an already-cancelled signal never opens a request", async () => {
  const ac = new AbortController();
  ac.abort();
  await expect(upload("/x", new FormData(), { signal: ac.signal })).rejects.toMatchObject({
    name: "AbortError",
  });
  expect(FakeXHR.all).toHaveLength(0);
});

test("a 401 refreshes once and sends again with the new token", async () => {
  refreshOk();
  const onReconnect = vi.fn();
  const onProgress = vi.fn();
  const p = upload("/x", new FormData(), { onProgress, onReconnect });
  await FakeXHR.all[0].respond(401, { detail: "expired" });
  await vi.waitFor(() => expect(FakeXHR.all).toHaveLength(2));
  expect(FakeXHR.all[1].headers.Authorization).toBe("Bearer new");
  await FakeXHR.all[1].respond(200, { done: true });
  await expect(p).resolves.toEqual({ done: true });
  // told it is reconnecting, never given a fake 0%
  expect(onReconnect).toHaveBeenCalledTimes(1);
  expect(onProgress).not.toHaveBeenCalled();
});

test("a second 401 is an error, not a loop", async () => {
  refreshOk();
  const p = upload("/x", new FormData());
  await FakeXHR.all[0].respond(401, { detail: "expired" });
  await vi.waitFor(() => expect(FakeXHR.all).toHaveLength(2));
  await FakeXHR.all[1].respond(401, { detail: "still no" });
  await expect(p).rejects.toMatchObject({ status: 401 });
  expect(FakeXHR.all).toHaveLength(2);
});

test("a failed refresh surfaces the 401", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 401 })),
  );
  const p = upload("/x", new FormData());
  await FakeXHR.all[0].respond(401, { detail: "expired" });
  await expect(p).rejects.toBeInstanceOf(ApiError);
});

test("server errors carry the server's message", async () => {
  const p = upload("/x", new FormData());
  await FakeXHR.all[0].respond(413, { detail: "File too large" });
  await expect(p).rejects.toMatchObject({ status: 413, message: "File too large" });
});

test("no connection is a TypeError, as with fetch", async () => {
  const p = upload("/x", new FormData());
  FakeXHR.all[0].onerror?.();
  await expect(p).rejects.toBeInstanceOf(TypeError);
});

test("a size the browser cannot compute reports no percentage", async () => {
  const onProgress = vi.fn();
  const p = upload("/x", new FormData(), { onProgress });
  FakeXHR.all[0].upload.onprogress?.({ lengthComputable: false, loaded: 10, total: 0 });
  await FakeXHR.all[0].respond(200, {});
  await p;
  expect(onProgress).not.toHaveBeenCalled();
});

test("onSent fires when the body has gone, before the answer", async () => {
  const onSent = vi.fn();
  const p = upload("/x", new FormData(), { onSent });
  FakeXHR.all[0].upload.onload?.();
  expect(onSent).toHaveBeenCalledTimes(1);
  await FakeXHR.all[0].respond(200, {});
  await p;
});

test("a 204 or empty answer resolves undefined, as api() does", async () => {
  const p = upload("/x", new FormData());
  const xhr = FakeXHR.all[0];
  xhr.status = 204;
  xhr.responseText = "";
  await xhr.onload?.();
  await expect(p).resolves.toBeUndefined();
});

test("a 2xx body that is not JSON rejects rather than resolving null", async () => {
  const p = upload("/x", new FormData());
  const xhr = FakeXHR.all[0];
  xhr.status = 200;
  xhr.responseText = "<html>proxy page</html>";
  await xhr.onload?.();
  await expect(p).rejects.toBeInstanceOf(ApiError);
});

test("a failure inside the retry path rejects instead of hanging", async () => {
  refreshOk();
  const p = upload("/x", new FormData());
  await FakeXHR.all[0].respond(401, { detail: "expired" });
  await vi.waitFor(() => expect(FakeXHR.all).toHaveLength(2));
  FakeXHR.all[1].onerror?.();
  await expect(p).rejects.toBeInstanceOf(TypeError);
});
