import { useCallback, useRef, useState } from "react";

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

/** A selection the server would refuse, caught first. The message is for the
    student: it names the file and the limit. */
export class UploadRefused extends Error {}

const mb = (bytes: number) => Math.ceil(bytes / (1024 * 1024));

/** Throws `UploadRefused` for too many files, one too big, or too big together. */
export function checkFiles(files: File[]): void {
  if (files.length > MAX_FILES_PER_UPLOAD) {
    throw new UploadRefused(
      `You picked ${files.length} files. The limit is ${MAX_FILES_PER_UPLOAD} per hand-in.`,
    );
  }
  for (const f of files) {
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
  if (!SHRINKABLE.has(file.type)) return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const size = shrunkSize(bitmap.width, bitmap.height);
    if (!size) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = size.w;
    canvas.height = size.h;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      bitmap.close();
      return file;
    }
    // JPEG has no alpha; a transparent PNG would otherwise turn black.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, size.w, size.h);
    ctx.drawImage(bitmap, 0, 0, size.w, size.h);
    bitmap.close();
    const blob = await new Promise<Blob | null>((res) =>
      canvas.toBlob(res, "image/jpeg", JPEG_QUALITY),
    );
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^./\\]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  }
}

/** Count check, shrink every photo, then size check on what will really be
    sent (a 24 MB photo is usually small once shrunk). */
export async function prepareFiles(files: File[]): Promise<File[]> {
  if (files.length > MAX_FILES_PER_UPLOAD) checkFiles(files);
  const out: File[] = [];
  for (const f of files) out.push(await shrinkImage(f));
  checkFiles(out);
  return out;
}

/** Runs one hand-in: prepares the files, then calls `send` with progress and
    an abort signal. `percent` is null before the upload starts. */
export function useUpload() {
  const [percent, setPercent] = useState<number | null>(null);
  const [preparing, setPreparing] = useState(false);
  const ctl = useRef<AbortController | null>(null);

  const run = useCallback(
    async <T>(
      files: File[],
      send: (
        prepared: File[],
        opts: { signal: AbortSignal; onProgress: (p: number) => void },
      ) => Promise<T>,
    ): Promise<T> => {
      const c = new AbortController();
      ctl.current = c;
      setPercent(null);
      setPreparing(true);
      try {
        const prepared = await prepareFiles(files);
        if (c.signal.aborted) throw new DOMException("Upload cancelled", "AbortError");
        setPreparing(false);
        setPercent(0);
        return await send(prepared, { signal: c.signal, onProgress: setPercent });
      } finally {
        setPreparing(false);
        setPercent(null);
      }
    },
    [],
  );
  const cancel = useCallback(() => ctl.current?.abort(), []);
  return { percent, preparing, run, cancel };
}
