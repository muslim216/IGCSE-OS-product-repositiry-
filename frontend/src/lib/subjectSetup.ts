/** A link into one section of Subject setup. When the caller knows which subject
 *  it is about, the tutor lands on that subject rather than the first one. */
export function subjectSetupPath(section: string, subjectId?: number | null): string {
  const query = subjectId == null ? "" : `?subject=${subjectId}`;
  return `/tutor/subject-setup${query}#${section}`;
}
