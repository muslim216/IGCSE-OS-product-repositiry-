import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myActivity } from "../api/me";
import { Card, EmptyState } from "../ui";

/**
 * Everything waiting on the tutor, across all their classes. The class pages
 * answer "how is this class doing"; this answers "what do I need to do next",
 * which previously had no home anywhere in the product.
 */
export default function ReviewQueuePage() {
  const activity = useQuery({ queryKey: ["activity"], queryFn: myActivity });

  if (activity.isLoading) return <p className="text-slate-500">Loading…</p>;
  const items = activity.data?.items ?? [];

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-900">Needs review</h2>
      <p className="text-sm text-slate-500">
        Work students have submitted that you haven't finalized yet.
      </p>

      {items.length === 0 ? (
        <EmptyState
          className="mt-5"
          icon="✅"
          title="Nothing waiting"
          description="When a student submits homework it appears here, already marked by the AI and ready for you to check."
          action={{ label: "Go to your classes", to: "/tutor" }}
        />
      ) : (
        <Card className="mt-5">
          <ul className="divide-y divide-slate-100">
            {items.map((item, i) => (
              <li key={`${item.kind}-${i}`}>
                <Link
                  to={item.link}
                  className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-muted"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-slate-800">{item.label}</span>
                    {item.sublabel && (
                      <span className="text-sm text-slate-500">{item.sublabel}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-sm text-brand-600">Review →</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
