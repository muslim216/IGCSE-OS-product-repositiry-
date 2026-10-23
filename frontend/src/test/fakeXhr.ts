import { vi } from "vitest";

/** Stubs XMLHttpRequest so an `upload()` answers on its own. `respond` runs on
    send and returns the status and body the "server" gives. For tests of the
    pages, which care what happens around an upload rather than its wire. */
export function stubXhr(respond: (url: string) => { status: number; body: unknown }) {
  const sent: { url: string; form: FormData }[] = [];
  class Auto {
    upload = { onprogress: null as ((e: unknown) => void) | null };
    status = 0;
    statusText = "";
    responseText = "";
    withCredentials = false;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private url = "";
    open(_method: string, url: string) {
      this.url = url;
    }
    setRequestHeader() {
      // The fake records no headers.
    }
    send(form: FormData) {
      sent.push({ url: this.url, form });
      const r = respond(this.url);
      setTimeout(() => {
        this.status = r.status;
        this.responseText = JSON.stringify(r.body);
        this.onload?.();
      }, 0);
    }
    abort() {
      this.onabort?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", Auto);
  return sent;
}
