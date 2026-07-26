import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../auth/AuthContext";
import { listGroups, myTodayLessons } from "../../api/groups";
import { assignmentsNeedingAttention } from "../../api/homework";
import { groupAnalytics } from "../../api/readiness";
import ReadinessTable, { type ReadinessFilter } from "../../components/ReadinessTable";
import { SectionCard, SectionHeader, useToast } from "../../components/ui";
import { deriveLearnerRows } from "../../lib/readiness";
import ActivityPanel from "./ActivityPanel";
import CreateLessonModal from "./CreateLessonModal";
import DashboardHeader from "./DashboardHeader";
import EvidenceToAction from "./EvidenceToAction";
import TeachingRhythm from "./TeachingRhythm";

/**
 * The educator's starting point, ordered as the MANARA loop:
 * teach today -> read the evidence -> decide the next step -> clear the queue.
 */
export default function TodayDashboard() {
  const { user } = useAuth();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [notifOpen, setNotifOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [filter, setFilter] = useState<ReadinessFilter>("all");
  const { toast, showToast } = useToast();

  const lessons = useQuery({ queryKey: ["today-lessons"], queryFn: myTodayLessons });
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });

  const groupList = groups.data ?? [];
  const analytics = useQueries({
    queries: groupList.map((g) => ({
      queryKey: ["analytics", g.id],
      queryFn: () => groupAnalytics(g.id),
      staleTime: 60_000,
    })),
  });

  const rows = deriveLearnerRows(
    groupList,
    analytics.map((a) => a.data),
  );
  const readinessLoading = groups.isLoading || analytics.some((a) => a.isLoading);
  const readinessError =
    groups.isError || (analytics.length > 0 && analytics.every((a) => a.isError));
  const capped = analytics.some((a) => (a.data?.weak_students.length ?? 0) >= 10);

  return (
    <div className="space-y-6">
      <DashboardHeader
        name={user?.name}
        searchOpen={searchOpen}
        onSearchToggle={() => {
          setSearchOpen((open) => !open);
          setSearchQuery("");
        }}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        notifOpen={notifOpen}
        onNotifToggle={() => setNotifOpen((open) => !open)}
        notifItems={attention.data}
        onCreateLesson={() => setCreateOpen(true)}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TeachingRhythm
            lessons={lessons.data}
            isLoading={lessons.isLoading}
            isError={lessons.isError}
          />
        </div>
        <ActivityPanel
          items={attention.data}
          isLoading={attention.isLoading}
          isError={attention.isError}
        />
      </div>

      <SectionCard>
        <SectionHeader
          title="Learner readiness"
          description="Weighted from every piece of marked evidence"
        />
        <div className="mt-4">
          <ReadinessTable
            rows={rows}
            filter={filter}
            onFilter={setFilter}
            searchQuery={searchQuery}
            loading={readinessLoading}
            error={readinessError}
            capped={capped}
          />
        </div>
      </SectionCard>

      <EvidenceToAction groups={groups.data} defaultGroupId={lessons.data?.[0]?.group_id} />

      <CreateLessonModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        groups={groups.data}
        onCreated={() => showToast("Lesson scheduled.")}
      />
      {toast}
    </div>
  );
}
