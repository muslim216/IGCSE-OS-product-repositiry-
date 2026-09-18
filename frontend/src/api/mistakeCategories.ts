import { api } from "./client";
import type { components } from "./schema";

// FE-4: aliases of the generated schema, never hand-written interfaces.
// `source` mirrors grade boundaries: "organization" is this org's own list;
// "none" means nothing is set and `categories` is the published starting
// point, not a choice anyone has made (PROD-8).
export type MistakeCategoryItem = components["schemas"]["MistakeCategoryItem"];
export type MistakeCategories = components["schemas"]["MistakeCategoriesOut"];

export const getMistakeCategories = (subjectId: number) =>
  api<MistakeCategories>(`/api/v1/subjects/${subjectId}/mistake-categories`);

export const saveMistakeCategories = (subjectId: number, categories: MistakeCategoryItem[]) =>
  api<MistakeCategories>(`/api/v1/subjects/${subjectId}/mistake-categories`, {
    method: "PUT",
    body: JSON.stringify({ categories }),
  });
