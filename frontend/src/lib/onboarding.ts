import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acknowledgeDefault,
  getOnboarding,
  type AcknowledgeableItem,
  type OnboardingItem,
  type OnboardingState,
} from "../api/onboarding";

/** The one query every setup surface reads. Saves invalidate this key so a
 *  label never outlives the value it describes. */
export const ONBOARDING_KEY = ["onboarding"] as const;

/** The server decides what is set up (`SEC-10`); this only reads it. A payload
 *  of the wrong shape is treated as a failed load rather than crashing a page
 *  the tutor opens every day. */
function isOnboardingState(data: unknown): data is OnboardingState {
  const d = data as Partial<OnboardingState> | null | undefined;
  return !!d && typeof d === "object" && !!d.account && Array.isArray(d.subjects);
}

export function useOnboarding() {
  return useQuery({
    queryKey: ONBOARDING_KEY,
    queryFn: async () => {
      const data = await getOnboarding();
      if (!isOnboardingState(data)) throw new Error("Unexpected onboarding response");
      return data;
    },
  });
}

/** "Keep the default": posts the acknowledgement and replaces the cache with the
 *  refreshed state the server returns. Not optimistic: the server is what says
 *  the item is reviewed. */
export function useAcknowledge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ item, subjectId }: { item: AcknowledgeableItem; subjectId: number | null }) =>
      acknowledgeDefault(item, subjectId),
    onSuccess: (data) => queryClient.setQueryData(ONBOARDING_KEY, data),
  });
}

export const ITEM_NAMES: Record<string, string> = {
  boundaries: "Grade boundaries",
  marking_rules: "Marking rules",
  mistake_categories: "Mistake categories",
  weak_threshold: "Weak-topic threshold",
  teaching_guidance: "Teaching guidance",
};

/** Item key to the Subject setup section where it is edited. */
export const ITEM_SECTIONS: Record<string, string> = {
  boundaries: "boundaries",
  marking_rules: "marking-rules",
  mistake_categories: "mistake-categories",
  weak_threshold: "preferences",
  teaching_guidance: "teaching-guidance",
};

/** The words for an item's state, where it is edited. Boundaries with none saved
 *  and guidance with nothing uploaded say what that means, because "Not set"
 *  alone hides that boundaries gate every predicted grade. */
export function stateLabel(item: Pick<OnboardingItem, "key" | "state">): string {
  switch (item.state) {
    case "default":
      return "Avora's default";
    case "reviewed":
      return "Default, reviewed by you";
    case "set_by_you":
      return "Set by you";
    case "not_set":
      if (item.key === "boundaries") return "Not set: no predicted grades for this subject yet";
      if (item.key === "teaching_guidance") return "Not set (optional)";
      return "Not set";
  }
}
