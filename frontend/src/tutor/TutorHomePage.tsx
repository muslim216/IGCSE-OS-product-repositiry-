import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { myTodayLessons, listGroups } from "../api/groups";
import { assignmentsNeedingAttention } from "../api/homework";
import { groupAnalytics } from "../api/readiness";
import {
  ArcadeButton,
  ArcadeEmpty,
  ArcadePanel,
  HealthBar,
  HighScoreTable,
  StatChip,
} from "../components/arcade";
import type { ArcadeButtonColor, HighScoreRow } from "../components/arcade";

const REASON_LABELS: Record<string, string> = {
  extraction_failed: "Question extraction failed",
  ai_failed: "AI marking failed",
  ai_marked: "AI-marked — awaiting your review",
};

const CYCLE_COLORS: ArcadeButtonColor[] = ["mint", "magenta", "gold"];

function firstName(name: string | undefined): string {
  return (name ?? "").split(" ")[0] || "there";
}

export default function TutorHomePage() {
  const { user } = useAuth();
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const lessons = useQuery({ queryKey: ["today-lessons"], queryFn: myTodayLessons });
  const attention = useQuery({ queryKey: ["assignments-attention"], queryFn: assignmentsNeedingAttention });

  const [groupId, setGroupId] = useState<number | null>(null);
  const activeId = groupId ?? groups.data?.[0]?.id ?? null;
  const analytics = useQuery({
    queryKey: ["analytics", activeId],
    queryFn: () => groupAnalytics(activeId as number),
    enabled: activeId !== null,
  });

  const totalStudents = (groups.data ?? []).reduce((sum, g) => sum + g.member_count, 0);

  const leaderboard: HighScoreRow[] = (analytics.data?.weak_students ?? [])
    .slice()
    .sort((a, b) => b.score - a.score)
    .map((s, i) => ({
      rank: i + 1,
      name: s.student_name,
      detail: s.subject_name,
      pct: s.score,
      to: `/tutor/students/${s.student_id}?group=${activeId}`,
    }));

  const topicEnergy = analytics.data?.weak_topics ?? [];
  const agreementRate = analytics.data?.agreement?.agreement_rate ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-black tracking-widest text-slate-100">
          Game Master: {firstName(user?.name)}
        </h2>
        <div className="arcade-trim mt-2 text-arcade-mint" aria-hidden="true" />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatChip label="Groups" value={String(groups.data?.length ?? 0)} />
        <StatChip label="Students" value={String(totalStudents)} />
        <StatChip
          label="Needs attention"
          value={String(attention.data?.length ?? 0)}
          color={!attention.data || attention.data.length === 0 ? "mint" : "gold"}
        />
      </div>

      <ArcadePanel
        title="Leaderboard & Analytics Matrix"
        accent="gold"
        action={
          groups.data && groups.data.length > 0 ? (
            <select
              className="border-2 border-black bg-arcade-panel-2 px-2 py-1 font-mono text-xs font-black uppercase tracking-wider text-slate-100"
              value={activeId ?? ""}
              onChange={(e) => setGroupId(Number(e.target.value))}
            >
              {groups.data.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      >
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <p className="mb-2 font-mono text-[10px] font-black uppercase tracking-wider text-arcade-mint">
              Readiness ranking
            </p>
            {analytics.isLoading ? (
              <ArcadeEmpty text="INSERT COIN..." blink />
            ) : (
              <HighScoreTable rows={leaderboard} />
            )}
          </div>

          <div>
            <p className="mb-2 font-mono text-[10px] font-black uppercase tracking-wider text-arcade-magenta">
              Topic energy
            </p>
            {topicEnergy.length > 0 ? (
              <ul className="space-y-2.5">
                {topicEnergy.map((t) => (
                  <li key={t.topic_code}>
                    <div className="flex items-center justify-between font-mono text-xs text-slate-300">
                      <span className="truncate">
                        {t.topic_code} {t.topic_title}
                      </span>
                      <span className="shrink-0 text-slate-500">x{t.student_count}</span>
                    </div>
                    <HealthBar value={t.avg_score} segments={10} />
                  </li>
                ))}
              </ul>
            ) : (
              <ArcadeEmpty text={analytics.isLoading ? "INSERT COIN..." : "NO DATA"} blink={analytics.isLoading} />
            )}
          </div>
        </div>

        {agreementRate !== null && (
          <p className="mt-4 border-t-4 border-black pt-3 font-mono text-xs font-black uppercase tracking-wider text-arcade-gold">
            Sync rate: {Math.round(agreementRate * 100)}%
          </p>
        )}
      </ArcadePanel>

      <div className="grid gap-4 md:grid-cols-2">
        <ArcadePanel title="Needs Your Attention" accent="magenta">
          <ul className="space-y-2.5">
            {attention.data?.slice(0, 5).map((a, i) => (
              <li key={i} className="font-mono text-sm">
                <Link
                  to={
                    a.submission_id
                      ? `/tutor/submissions/${a.submission_id}`
                      : `/tutor/assignments/${a.assignment_id}`
                  }
                  className="block truncate text-arcade-mint hover:text-arcade-gold"
                >
                  <span className="mr-2 font-black text-arcade-magenta">[!]</span>
                  {a.assignment_title}
                  {a.student_name && <span className="text-slate-500"> — {a.student_name}</span>}
                </Link>
                <p className="mt-0.5 truncate pl-5 text-xs text-arcade-gold">
                  {REASON_LABELS[a.reason] ?? a.reason}
                </p>
              </li>
            ))}
            {attention.data?.length === 0 && <ArcadeEmpty text="ALL CLEAR" />}
          </ul>
        </ArcadePanel>

        <ArcadePanel title="Today's Lessons" accent="mint">
          <ul className="space-y-1.5">
            {lessons.data?.map((l) => (
              <li key={l.id} className="flex items-center justify-between font-mono text-sm text-slate-200">
                <span>{l.group_name}</span>
                <span className="text-slate-500">{l.start_time.slice(0, 5)}</span>
              </li>
            ))}
            {lessons.data?.length === 0 && <ArcadeEmpty text="NO LESSONS TODAY" />}
          </ul>
        </ArcadePanel>
      </div>

      <ArcadePanel title="Select Stage" accent="mint">
        {groups.data && groups.data.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.data.map((g, i) => (
              <ArcadeButton
                key={g.id}
                to={`/tutor/groups/${g.id}`}
                color={CYCLE_COLORS[i % CYCLE_COLORS.length]}
                className="!flex-col !items-stretch !gap-1 !normal-case"
              >
                <span className="truncate">{g.name}</span>
                <span className="font-mono text-[10px] normal-case tracking-normal opacity-80">
                  {g.subject.exam_board} {g.subject.code} · {g.member_count}P
                </span>
              </ArcadeButton>
            ))}
          </div>
        ) : (
          <ArcadeEmpty text="NO GROUPS YET" />
        )}
      </ArcadePanel>
    </div>
  );
}
