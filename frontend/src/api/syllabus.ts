import type { components } from "./schema";
import { api } from "./client";

export type Topic = components["schemas"]["TopicOut"];

export const listTopics = (subjectId: number) =>
  api<Topic[]>(`/api/v1/subjects/${subjectId}/topics`);
