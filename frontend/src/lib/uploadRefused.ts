/** A selection the server would refuse, caught before sending. The message is
    for the student: it names the file and the limit. Kept apart from the
    upload hook so `errors.ts` can recognise it without importing React code. */
export class UploadRefused extends Error {}

export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}
