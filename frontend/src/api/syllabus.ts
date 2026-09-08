import { api } from "./client";
import type { components } from "./schema";

export interface Topic {
  id: number;
  code: string;
  title: string;
  parent_id: number | null;
  weight: number;
}

export const listTopics = (subjectId: number) =>
  api<Topic[]>(`/api/v1/subjects/${subjectId}/topics`);

/** A chapter of a subject's syllabus (`AV-9`). A subject whose syllabus was
 *  never extracted chapter-first legitimately has none, and an empty list is
 *  that answer rather than a failure. */
export type Chapter = components["schemas"]["ChapterOut"];

export const listChapters = (subjectId: number) =>
  api<Chapter[]>(`/api/v1/subjects/${subjectId}/chapters`);
