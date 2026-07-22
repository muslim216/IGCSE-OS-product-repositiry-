import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { WEEKDAYS, myLessons } from "../api/groups";
import { myReadiness } from "../api/readiness";
import { myAssignments, type StudentAssignment } from "../api/homework";
import { myAssessmentScores } from "../api/readiness";
import { listConversations } from "../api/chat";
import {
  ArcadeButton,
  ArcadeEmpty,
  ArcadePanel,
  CountdownTimer,
  GradeBadge,
  HealthBar,
  StatChip,
} from "../components/arcade";
import type { ArcadeButtonColor } from "../components/arcade";

const CYCLE_COLORS: ArcadeButtonColor[] = ["mint", "magenta", "gold"];

const STATUS_GLYPH: Record<string, { glyph: string; color: string }> = {
  not_submitted: { glyph: "[ ]", color: "text-arcade-gold" },
  submitted: { glyph: "[>]", color: "text-arcade-mint" },
  being_marked: { glyph: "[>]", color: "text-arcade-mint" },
  marked: { glyph: "[x]", color: "text-arcade-mint" },
};

function firstName(name: string | undefined): string {
  return (name ?? "").split(" ")[0] || "there";
}

function dueLabel(due: string | null): string {
  if (!due) return "NO DUE DATE";
  return new Date(due)
    .toLocaleDateString(undefined, { day: "numeric", month: "short" })
    .toUpperCase();
}

function compareDue(a: StudentAssignment, b: StudentAssignment): number {
  if (!a.due_at && !b.due_at) return 0;
  if (!a.due_at) return 1;
  if (!b.due_at) return -1;
  return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
}

export default function StudentHomePage() {
  const { user } = useAuth();
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });
  const lessons = useQuery({ queryKey: ["my-lessons"], queryFn: myLessons });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: listConversations });
  const scores = useQuery({ queryKey: ["my-assessment-scores"], queryFn: myAssessmentScores });

  const subjects = readiness.data?.subjects ?? [];
  const scored = subjects.filter((s) => s.score !== null);
  const overall =
    scored.length > 0
      ? Math.round(scored.reduce((sum, s) => sum + (s.score ?? 0), 0) / scored.length)
      : null;

  const due = (assignments.data ?? [])
    .filter((a) => a.submission_status === "not_submitted")
    .sort(compareDue);
  const activeQuest = due[0];
  const questLog = (assignments.data ?? []).slice(0, 5);
  const nextLesson = lessons.data?.[0];

  const weakTopics = subjects
    .flatMap((s) => s.weak_topics.map((t) => ({ ...t, subject_name: s.subject_name })))
    .slice(0, 3);

  const latestChat = conversations.data?.[0];
  const recentScores = (scores.data ?? []).slice(0, 6);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-black tracking-widest text-slate-100">
          Player 1: {firstName(user?.name)}
        </h2>
        <div className="arcade-trim mt-2 text-arcade-mint" aria-hidden="true" />
        <p className="mt-2 font-mono text-xs uppercase tracking-wider text-arcade-gold">Ready?</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatChip
          label="Readiness"
          value={overall !== null ? `${overall}%` : "--"}
          color={overall === null ? "default" : overall >= 70 ? "mint" : "gold"}
        />
        <StatChip
          label="Homework due"
          value={String(due.length)}
          color={due.length === 0 ? "mint" : "gold"}
        />
        <StatChip
          label="Next lesson"
          value={nextLesson ? `${WEEKDAYS[nextLesson.weekday]} ${nextLesson.start_time.slice(0, 5)}` : "--"}
        />
      </div>

      <ArcadePanel title="Active Quest" accent="gold">
        {activeQuest ? (
          <div className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-mono text-lg font-black uppercase text-slate-100">{activeQuest.title}</p>
                <p className="mt-1 font-mono text-xs text-slate-400">
                  {activeQuest.subject_name} · {activeQuest.question_count} questions ·{" "}
                  {activeQuest.total_marks} marks
                </p>
              </div>
              {activeQuest.due_at ? (
                <CountdownTimer target={activeQuest.due_at} />
              ) : (
                <span className="font-mono text-sm font-black uppercase tracking-wider text-arcade-mint">
                  No time limit
                </span>
              )}
            </div>
            <ArcadeButton to={`/student/homework/${activeQuest.id}`} color="gold">
              Start Quest --&gt;
            </ArcadeButton>
          </div>
        ) : assignments.isLoading ? (
          <ArcadeEmpty text="INSERT COIN..." blink />
        ) : (
          <ArcadeEmpty text="ALL QUESTS CLEARED" />
        )}

        {questLog.length > 0 && (
          <div className="mt-5 border-t-4 border-black pt-3">
            <p className="mb-2 font-mono text-[10px] font-black uppercase tracking-wider text-slate-500">
              Quest log
            </p>
            <ul className="space-y-1.5">
              {questLog.map((a) => {
                const glyph = STATUS_GLYPH[a.submission_status ?? "not_submitted"] ?? STATUS_GLYPH.not_submitted;
                return (
                  <li key={a.id}>
                    <Link
                      to={`/student/homework/${a.id}`}
                      className="flex items-center justify-between gap-3 font-mono text-sm hover:bg-white/5"
                    >
                      <span className="truncate">
                        <span className={`mr-2 font-black ${glyph.color}`}>{glyph.glyph}</span>
                        <span className="text-slate-200">{a.title}</span>
                      </span>
                      <span className="shrink-0 text-slate-500">
                        {a.submission_status === "marked" && a.my_total !== null
                          ? `${a.my_total}/${a.total_marks}`
                          : dueLabel(a.due_at)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </ArcadePanel>

      <ArcadePanel title="Subject Select" accent="magenta">
        {subjects.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {subjects.map((s, i) => (
              <ArcadeButton
                key={s.subject_id}
                to="/student/readiness"
                color={CYCLE_COLORS[i % CYCLE_COLORS.length]}
                className="!flex-col !items-stretch !gap-2 !normal-case"
              >
                <div className="flex items-center justify-between">
                  <span className="truncate">{s.subject_name}</span>
                  <GradeBadge pct={s.score} size="sm" />
                </div>
                <HealthBar value={s.score ?? 0} segments={8} />
              </ArcadeButton>
            ))}
          </div>
        ) : (
          <ArcadeEmpty text={readiness.isLoading ? "INSERT COIN..." : "NO SUBJECTS YET"} blink={readiness.isLoading} />
        )}

        {weakTopics.length > 0 && (
          <div className="mt-4 space-y-1 border-t-4 border-black pt-3">
            {weakTopics.map((t) => (
              <p key={t.topic_id} className="font-mono text-xs text-arcade-gold">
                [!] {t.topic_code} {t.topic_title}{" "}
                <span className="text-slate-500">— {t.subject_name}</span>
              </p>
            ))}
          </div>
        )}
      </ArcadePanel>

      <ArcadePanel
        title="High Scores"
        accent="gold"
        action={
          <Link
            to="/student/exams"
            className="font-mono text-[10px] font-black uppercase tracking-wider text-arcade-mint hover:text-arcade-gold"
          >
            All --&gt;
          </Link>
        }
      >
        {recentScores.length > 0 ? (
          <ul className="divide-y-2 divide-black">
            {recentScores.map((s, i) => (
              <li key={`${s.assessment_id}-${i}`} className="flex items-center gap-3 py-2">
                <GradeBadge pct={s.pct} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-sm font-black uppercase text-slate-100">{s.title}</p>
                  <p className="font-mono text-xs text-slate-500">
                    {s.subject_name} ·{" "}
                    {new Date(s.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                  </p>
                </div>
                <span className="shrink-0 font-mono text-xs font-black text-arcade-gold">
                  {s.marks}/{s.max_marks}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <ArcadeEmpty text={scores.isLoading ? "INSERT COIN..." : "NO SCORES YET"} blink={scores.isLoading} />
        )}
      </ArcadePanel>

      <ArcadePanel title="AI Tutor" accent="mint">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="min-w-0 truncate font-mono text-sm text-slate-400">
            {latestChat ? `Continue: "${latestChat.title}"` : "Stuck on a concept? Ask your AI tutor."}
          </p>
          <ArcadeButton to="/student/tutor" color="dark">
            {latestChat ? "Continue Game -->" : "New Game -->"}
          </ArcadeButton>
        </div>
      </ArcadePanel>
    </div>
  );
}
