import { api } from "./client";
import type { components } from "./schema";

/** What is set up, decided by the backend from the data (task 9.1a). A frontend
 *  gate is never the control (`SEC-10`): this is only what it shows. */
export type OnboardingState = components["schemas"]["OnboardingState"];
export type OnboardingSubject = components["schemas"]["SubjectStatus"];
export type OnboardingItem = components["schemas"]["ItemStatus"];
export type OnboardingClass = components["schemas"]["ClassStatus"];
export type OnboardingNextStep = components["schemas"]["NextStep"];
export type AcknowledgeableItem = components["schemas"]["AcknowledgementIn"]["item"];

export const getOnboarding = () => api<OnboardingState>("/api/v1/onboarding");

/** "I looked at this default and keep it." Idempotent; returns the refreshed
 *  state. `subjectId` is null only for the account-level item. */
export const acknowledgeDefault = (item: AcknowledgeableItem, subjectId: number | null) =>
  api<OnboardingState>("/api/v1/onboarding/acknowledgements", {
    method: "POST",
    body: JSON.stringify({ item, subject_id: subjectId }),
  });
