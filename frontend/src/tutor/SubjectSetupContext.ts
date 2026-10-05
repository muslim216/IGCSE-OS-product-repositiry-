import { createContext, useContext } from "react";

/**
 * The one subject Subject setup is showing. The five subject pages each used
 * to carry their own picker; on that page the tutor chooses once and every
 * section follows. Outside the page the context is absent (`null`) and each
 * page behaves exactly as it did standing alone, which is why they keep their
 * own picker and state for that case.
 */
export interface SubjectSetupValue {
  /** `null` until the subject list has loaded. */
  subjectId: number | null;
  setSubjectId: (id: number) => void;
}

export const SubjectSetupContext = createContext<SubjectSetupValue | null>(null);

export const useSubjectSetup = () => useContext(SubjectSetupContext);
