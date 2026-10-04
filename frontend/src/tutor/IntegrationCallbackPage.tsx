import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { completeIntegration, PROVIDER_LABEL, type MeetingProvider } from "../api/integrations";
import { PageHeader } from "../components/page";
import { friendlyError } from "../lib/errors";
import { stateKey } from "./IntegrationsSetting";

function isProvider(value: string | undefined): value is MeetingProvider {
  return value === "zoom" || value === "google_meet";
}

/** Where Zoom or Google sends the browser back to. It hands the one-time code and
 *  the signed `state` to the API under the tutor's own session; the API is what
 *  verifies the state. The copy kept in this browser is a second check only. */
export default function IntegrationCallbackPage() {
  const { provider } = useParams();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const code = params.get("code");
  const state = params.get("state");
  const denied = params.get("error");
  // A code is single-use: React strict mode must not spend it twice.
  const started = useRef(false);

  const finish = useMutation({
    mutationFn: (p: MeetingProvider) => completeIntegration(p, code ?? "", state ?? ""),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });

  const label = isProvider(provider) ? PROVIDER_LABEL[provider] : "the provider";
  // Decided once, on arrival: the stored copy is removed as soon as it is used, and
  // reading it again after that would turn a success into a complaint.
  const [problem] = useState<string | null>(() =>
    !isProvider(provider)
      ? "That isn't a connection we know about."
      : denied
        ? `${label} said no — nothing was connected. You can try again from Settings.`
        : !code || !state
          ? `${label} didn't send back what we need. Try connecting again from Settings.`
          : sessionStorage.getItem(stateKey(provider)) !== state
            ? "This connection attempt didn't start in this browser, or it took too long. Try connecting again from Settings."
            : null,
  );

  useEffect(() => {
    if (started.current || problem !== null || !isProvider(provider)) return;
    started.current = true;
    finish.mutate(provider);
    sessionStorage.removeItem(stateKey(provider));
  }, [problem, provider, finish]);

  return (
    <div className="max-w-2xl">
      <PageHeader title={`Connecting ${label}`} />
      {problem ? (
        <p role="alert" className="text-sm text-risk-600">
          {problem}
        </p>
      ) : finish.isError ? (
        <p role="alert" className="text-sm text-risk-600">
          {friendlyError(finish.error)}
        </p>
      ) : finish.isSuccess ? (
        <p role="status" className="text-sm text-ok-700">
          {label} is connected.
        </p>
      ) : (
        <p className="text-sm text-ink-500">Finishing the connection…</p>
      )}
      <p className="mt-4 text-sm">
        <Link to="/tutor/settings" className="text-brand-700 underline">
          Back to Settings
        </Link>
      </p>
    </div>
  );
}
