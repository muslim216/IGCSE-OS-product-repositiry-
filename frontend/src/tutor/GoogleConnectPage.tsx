import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { disconnectGoogle, googleAccount, startGoogleOAuth } from "../api/googleClassroom";
import { Button, Card, CardBody, CardHeader } from "../ui";

const CALLBACK_MESSAGE: Record<string, { tone: "ok" | "warn"; text: string }> = {
  connected: { tone: "ok", text: "Google Classroom connected." },
  missing_scopes: {
    tone: "warn",
    text: "Connected, but some permissions weren't granted. Reconnect and accept all of them, or importing won't work.",
  },
  error: { tone: "warn", text: "Google sign-in didn't complete. Try connecting again." },
};

export default function GoogleConnectPage() {
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const account = useQuery({ queryKey: ["google-account"], queryFn: googleAccount });

  const connect = useMutation({
    mutationFn: startGoogleOAuth,
    // Leaves the SPA for Google's consent screen; it comes back to this route.
    onSuccess: (data) => {
      window.location.href = data.authorize_url;
    },
  });
  const disconnect = useMutation({
    mutationFn: disconnectGoogle,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["google-account"] }),
  });

  const callback = CALLBACK_MESSAGE[params.get("google") ?? ""];
  const data = account.data;

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-semibold text-slate-900">Google Classroom</h2>
      <p className="mt-1 text-sm text-slate-500">
        Connect your Google account to pull work students hand in on Classroom into a class here,
        where it goes through the same AI marking as anything else.
      </p>

      {callback && (
        <div
          className={`mt-4 rounded-card border p-3 text-sm ${
            callback.tone === "ok"
              ? "border-ready-500/30 bg-ready-50 text-ready-600"
              : "border-caution-500/30 bg-caution-50 text-caution-600"
          }`}
        >
          {callback.text}
        </div>
      )}

      {data && !data.configured && (
        <div className="mt-4 rounded-card border border-caution-500/30 bg-caution-50 p-3 text-sm text-caution-600">
          Google Classroom isn't set up on this server yet. It needs GOOGLE_CLIENT_ID,
          GOOGLE_CLIENT_SECRET and GOOGLE_TOKEN_KEY to be configured.
        </div>
      )}

      <Card className="mt-4">
        <CardHeader
          title={data?.connected ? "Connected" : "Not connected"}
          description={data?.google_email ?? undefined}
          actions={
            data?.connected ? (
              <Button
                variant="secondary"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                onClick={() => connect.mutate()}
                disabled={connect.isPending || !data?.configured}
              >
                Connect Google
              </Button>
            )
          }
        />
        <CardBody>
          {data?.status === "needs_reauth" && (
            <div className="mb-3 rounded-control border border-caution-500/30 bg-caution-50 p-3 text-sm text-caution-600">
              <p className="font-medium">Reconnect needed</p>
              <p className="mt-1">{data.last_error ?? "Google access has expired."}</p>
              <Button className="mt-2" size="sm" onClick={() => connect.mutate()}>
                Reconnect
              </Button>
            </div>
          )}
          {data?.missing_scopes.length ? (
            <p className="mb-3 text-sm text-risk-600">
              Missing permissions: {data.missing_scopes.map((s) => s.split("/").pop()).join(", ")}
            </p>
          ) : null}
          <p className="text-sm text-slate-500">
            Access is read-only: we list your courses and coursework, read who turned work in, and
            download their attachments. Nothing is written back to Classroom, and grades stay
            here.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
