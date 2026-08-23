/** Zone helpers shared by the organization picker and the per-user one.
 *
 * They live here rather than in either component because the per-user control
 * (AV-67) is mounted for students and parents too, and a shared control
 * reaching into `tutor/` for its list would invert the folder layering the
 * first time someone moved a file.
 */

/** Every IANA zone this browser knows, for the picker.
 *
 * Intl.supportedValuesOf is recent enough that it may be absent; when it is,
 * the control degrades to offering the detected zone alone rather than
 * disappearing. An empty list is a smaller UI, not a broken one. */
export function supportedTimezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    return intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

export function detectedTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}
