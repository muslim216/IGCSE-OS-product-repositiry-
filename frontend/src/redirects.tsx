import type { ReactNode } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "./api/groups";
import { PageSkeleton } from "./components/page";

/** A redirect that keeps the `?query` and the `#hash` of the link it replaces.
    A hash never reaches the server, so dropping it here would lose it for good.
    A fixed `hash` is the section to open when the old link named none. */
export function Keep({ to, hash }: { to: string; hash?: string }) {
  const location = useLocation();
  return (
    <Navigate to={{ pathname: to, search: location.search, hash: location.hash || hash }} replace />
  );
}

/** Where a page that used to be a menu item now lives: inside a class. A tutor
    with exactly one class goes straight to the tab; with several, the class
    list opens with a one-line tip saying where the page went. */
export function MovedToClass({
  tab,
  hash,
  tip,
  tipId,
}: {
  tab: "homework" | "analytics";
  hash: string;
  tip: string;
  /** Names the tip so dismissing it is remembered for it alone. */
  tipId: string;
}) {
  const location = useLocation();
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  if (groups.isPending) return <PageSkeleton rows={3} label="Finding your class" />;
  const only = groups.data?.length === 1 ? groups.data[0] : null;
  return only ? (
    <Navigate
      to={{
        pathname: `/tutor/groups/${only.id}/${tab}`,
        search: location.search,
        hash: location.hash || hash,
      }}
      replace
    />
  ) : (
    <Navigate
      to={{ pathname: "/tutor/classes", search: location.search, hash: location.hash }}
      state={{ tip, tipId }}
      replace
    />
  );
}

/** The old per-class report address, now a section of the class's Progress tab. */
export function ReportRedirect() {
  const { groupId } = useParams();
  return <Keep to={`/tutor/groups/${groupId}/analytics`} hash="#reports" />;
}

/** The old to-do link to one past paper (`#paper-N`) now goes to the
    all-subjects shelf, which can act on any paper; any other old past-papers
    address goes to the class Work tab as before. */
export function PastPapersEntry({ children }: { children: ReactNode }) {
  const location = useLocation();
  return location.hash.startsWith("#paper-") ? (
    <Keep to="/tutor/past-papers/all" />
  ) : (
    <>{children}</>
  );
}
