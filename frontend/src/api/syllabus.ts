import { api } from "./client";

export interface Topic {
  id: number;
  code: string;
  title: string;
  parent_id: number | null;
  weight: number;
}

export const listTopics = (subjectId: number) =>
  api<Topic[]>(`/api/v1/subjects/${subjectId}/topics`);
