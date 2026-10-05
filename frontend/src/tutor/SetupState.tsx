import { Button } from "../components/controls";
import { friendlyError } from "../lib/errors";
import { ITEM_NAMES, stateLabel, useAcknowledge, useOnboarding } from "../lib/onboarding";
import type { AcknowledgeableItem, OnboardingItem } from "../api/onboarding";
import { useSubjectSetup } from "./SubjectSetupContext";

const ACKNOWLEDGEABLE = new Set([
  "boundaries",
  "marking_rules",
  "mistake_categories",
  "weak_threshold",
]);

/**
 * Whether a value is Avora's default or the tutor's own, shown where it is
 * edited (9.1d). Reads the same query as the Setup checklist, so a label and the
 * checklist cannot disagree. While that query is loading or has failed it shows
 * nothing: no label is better than a wrong one. The text carries the meaning,
 * never colour alone.
 *
 * The subject comes from Subject setup, so the embedded pages pass only the
 * item. `account` is the account-level item, which has no subject.
 */
export default function SetupState({
  item,
  account = false,
  prefix,
}: {
  item?: string;
  account?: boolean;
  prefix?: string;
}) {
  const setup = useSubjectSetup();
  const onboarding = useOnboarding();
  const acknowledge = useAcknowledge();

  const data = onboarding.data;
  if (!data) return null;

  let found: OnboardingItem | undefined;
  let subjectId: number | null = null;
  let subjectName = "";
  if (account) {
    found = data.account;
  } else {
    // Outside Subject setup there is no subject to describe.
    if (!setup || setup.subjectId === null) return null;
    const subject = data.subjects.find((s) => s.subject_id === setup.subjectId);
    found = subject?.items.find((i) => i.key === item);
    subjectId = setup.subjectId;
    subjectName = subject?.subject_name ?? "";
  }
  if (!found) return null;

  const key = found.key;
  const canKeep = found.state === "default" && (account || ACKNOWLEDGEABLE.has(key));
  const name = account ? "account settings" : `${ITEM_NAMES[key] ?? key}, ${subjectName}`;
  const pressed =
    acknowledge.isPending &&
    acknowledge.variables?.item === key &&
    acknowledge.variables.subjectId === subjectId;

  return (
    <>
      <span className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-700">
        {prefix ? `${prefix}: ` : ""}
        {stateLabel(found)}
      </span>
      {canKeep && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={acknowledge.isPending}
          aria-label={`${account ? "Keep the defaults for" : "Keep the default for"} ${name}`}
          onClick={() => acknowledge.mutate({ item: key as AcknowledgeableItem, subjectId })}
        >
          {pressed ? "Saving" : account ? "Keep the defaults" : "Keep the default"}
        </Button>
      )}
      {acknowledge.isError && (
        <span role="alert" className="text-xs text-risk-600">
          {friendlyError(acknowledge.error)}
        </span>
      )}
    </>
  );
}
