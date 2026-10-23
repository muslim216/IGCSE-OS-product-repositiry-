import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { UploadRefused, isAbort } from "./uploadRefused";

// Mirrors of the backend's limits, so a bad selection is refused before any
// bytes leave the phone. Keep in step with:
//   MAX_FILE_BYTES            backend/app/services/storage.py   (20 MB a file)
//   max_files_per_upload      backend/app/config.py             (40 a hand-in)
//   max_upload_request_mb     backend/app/config.py             (150 MB a request)
// The server still enforces all three; these only save the wait.
export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_FILES_PER_UPLOAD = 40;
export const MAX_REQUEST_BYTES = 150 * 1024 * 1024;

// The AI provider refuses images much over this when a hand-in has many pages.
export const MAX_IMAGE_SIDE = 2000;
export const JPEG_QUALITY = 0.85;
// HEIC is deliberately absent: browsers mostly cannot decode it, and the
// server transcodes it (storage.py). PDFs are not images.
const SHRINKABLE = new Set(["image/jpeg", "image/png", "image/webp"]);
// Some phones and file pickers give no MIME type at all; fall back to the name.
const SHRINKABLE_NAME = /\.(jpe?g|png|webp)$/i;

const mb = (bytes: number) => Math.ceil(bytes / (1024 * 1024));
const cancelled = () => new DOMException("Upload cancelled", "AbortError");

/** Throws `UploadRefused` for too many files, an empty one, one too big, or
    too big together. */
export function checkFiles(files: File[]): void {
  if (files.length > MAX_FILES_PER_UPLOAD) {
    throw new UploadRefused(
      `You picked ${files.length} files. The limit is ${MAX_FILES_PER_UPLOAD} per hand-in.`,
    );
  }
  for (const f of files) {
    if (f.size === 0) {
      throw new UploadRefused(`${f.name} is empty. Pick it again, or leave it out.`);
    }
    if (f.size > MAX_FILE_BYTES) {
      throw new UploadRefused(
        `${f.name} is too big (${mb(f.size)} MB). The limit is ${mb(MAX_FILE_BYTES)} MB per file.`,
      );
    }
  }
  const total = files.reduce((n, f) => n + f.size, 0);
  if (total > MAX_REQUEST_BYTES) {
    throw new UploadRefused(
      `These files add up to ${mb(total)} MB. The limit is ${mb(MAX_REQUEST_BYTES)} MB per hand-in.`,
    );
  }
}

/** Longest side scaled to `MAX_IMAGE_SIDE`, or null when it is small enough. */
export function shrunkSize(width: number, height: number): { w: number; h: number } | null {
  const longest = Math.max(width, height);
  if (longest <= MAX_IMAGE_SIDE) return null;
  const k = MAX_IMAGE_SIDE / longest;
  return { w: Math.max(1, Math.round(width * k)), h: Math.max(1, Math.round(height * k)) };
}

/** A JPEG no longer than `MAX_IMAGE_SIDE`, or the original file when it is not
    a shrinkable image, is small already, cannot be decoded, or would not get
    smaller. Never throws: an upload is not worth losing over an optimisation. */
export async function shrinkImage(file: File): Promise<File> {
  const shrinkable = SHRINKABLE.has(file.type) || (!file.type && SHRINKABLE_NAME.test(file.name));
  if (!shrinkable) return file;
  let bitmap: ImageBitmap | undefined;
  let canvas: HTMLCanvasElement | undefined;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const size = shrunkSize(bitmap.width, bitmap.height);
    if (!size) return file;
    canvas = document.createElement("canvas");
    canvas.width = size.w;
    canvas.height = size.h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    // JPEG has no alpha; a transparent PNG would otherwise turn black.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, size.w, size.h);
    ctx.drawImage(bitmap, 0, 0, size.w, size.h);
    const c = canvas;
    const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/jpeg", JPEG_QUALITY));
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^./\\]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  } finally {
    // A phone has little memory to spare across 15 photos: give both back now
    // rather than when the garbage collector gets round to it.
    bitmap?.close();
    if (canvas) canvas.width = canvas.height = 0;
  }
}

/** Count check, shrink every photo, then size check on what will really be
    sent (a 24 MB photo is usually small once shrunk). Stops between photos
    when `signal` is aborted. */
export async function prepareFiles(files: File[], signal?: AbortSignal): Promise<File[]> {
  if (files.length > MAX_FILES_PER_UPLOAD) checkFiles(files);
  const out: File[] = [];
  for (const f of files) {
    if (signal?.aborted) throw cancelled();
    out.push(await shrinkImage(f)); // NOSONAR sequential on purpose: one decoded image in memory at a time, abort checked per file
  }
  if (signal?.aborted) throw cancelled();
  checkFiles(out);
  return out;
}

export type UploadPhase = "idle" | "preparing" | "sending" | "processing" | "reconnecting";

export interface SendOptions {
  signal: AbortSignal;
  onProgress: (percent: number) => void;
  onSent: () => void;
  onReconnect: () => void;
}

export type UploadState = ReturnType<typeof useUpload>;

/** Runs one hand-in: prepares the files, then calls `send` with progress and
    an abort signal. `percent` stays null until the browser reports a real
    figure (`PROD-2`: no invented 0%). */
export function useUpload() {
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [percent, setPercent] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [wasCancelled, setWasCancelled] = useState(false);
  const [attention, setAttention] = useState(0);
  const ctl = useRef<AbortController | null>(null);
  const milestone = useRef(0);
  const submitRef = useRef<HTMLButtonElement>(null);

  const phaseRef = useRef<UploadPhase>("idle");
  const alive = useRef(true);
  const go = useCallback((p: UploadPhase) => {
    phaseRef.current = p;
    setPhase(p);
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      // Leaving mid-prepare or mid-send abandons a request nobody can cancel.
      // Once every byte is sent (or while a refresh is retrying) the server may
      // already be committing it: let it finish so onSuccess still refreshes
      // the data, rather than abort and leave a hand-in half-known.
      const p = phaseRef.current;
      if (p === "preparing" || p === "sending") ctl.current?.abort();
    };
  }, []);

  const run = useCallback(
    async <T>(files: File[], send: (prepared: File[], opts: SendOptions) => Promise<T>) => {
      ctl.current?.abort();
      const c = new AbortController();
      ctl.current = c;
      // A late callback from a superseded run must not touch the new one's state.
      const mine = () => alive.current && ctl.current === c;
      milestone.current = 0;
      setWasCancelled(false);
      setPercent(null);
      go("preparing");
      setAnnouncement("Getting your photos ready");
      try {
        const prepared = await prepareFiles(files, c.signal);
        if (!mine()) throw cancelled();
        go("sending");
        setAnnouncement("Sending");
        const result = await send(prepared, {
          signal: c.signal,
          onProgress: (p) => {
            if (!mine()) return;
            setPercent(p);
            if (p >= 100) {
              go("processing");
              return;
            }
            go("sending");
            // Milestones only: a screen reader reading every percent is noise.
            const m = [75, 50, 25].find((x) => p >= x) ?? 0;
            if (m > milestone.current) {
              milestone.current = m;
              setAnnouncement(`Sending, ${m} percent`);
            }
          },
          onSent: () => {
            if (!mine()) return;
            go("processing");
            setAnnouncement("Processing");
          },
          onReconnect: () => {
            if (!mine()) return;
            milestone.current = 0;
            setPercent(null);
            go("reconnecting");
            setAnnouncement("Reconnecting");
          },
        });
        if (mine()) setAnnouncement("Sent");
        return result;
      } catch (e) {
        if (mine()) {
          if (isAbort(e)) {
            setWasCancelled(true);
            setAnnouncement("Upload cancelled. Your files are still here.");
          } else {
            setAnnouncement("");
          }
          setAttention((n) => n + 1);
        }
        throw e;
      } finally {
        if (mine()) {
          go("idle");
          setPercent(null);
        }
      }
    },
    [go],
  );
  const cancel = useCallback(() => ctl.current?.abort(), []);
  return {
    phase,
    percent,
    announcement,
    cancelled: wasCancelled,
    attention,
    submitRef,
    run,
    cancel,
  };
}

/** After a refusal, failure or cancel, put focus back on the submit button so
    the retry is one key press away. Waits until the button is enabled again. */
export function useFocusSubmitOnFailure(up: UploadState, isPending: boolean) {
  const handled = useRef(0);
  const ref: RefObject<HTMLButtonElement | null> = up.submitRef;
  useEffect(() => {
    if (!isPending && up.attention !== handled.current) {
      handled.current = up.attention;
      ref.current?.focus();
    }
  });
}
