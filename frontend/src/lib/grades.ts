export type Grade = "A*" | "A" | "B" | "C" | "D" | "E" | "F" | "G" | "U";

export interface GradeInfo {
  grade: Grade;
  bg: string;
  text: string;
}

const BOUNDARIES: { min: number; grade: Grade; bg: string; text: string }[] = [
  { min: 90, grade: "A*", bg: "bg-arcade-gold", text: "text-[#050308]" },
  { min: 80, grade: "A", bg: "bg-arcade-mint", text: "text-[#050308]" },
  { min: 70, grade: "B", bg: "bg-[#66ffe0]", text: "text-[#050308]" },
  { min: 60, grade: "C", bg: "bg-[#ffe066]", text: "text-[#050308]" },
  { min: 50, grade: "D", bg: "bg-[#ff66a8]", text: "text-[#050308]" },
  { min: 40, grade: "E", bg: "bg-[#a06cd5]", text: "text-white" },
  { min: 30, grade: "F", bg: "bg-[#8a5bb8]", text: "text-white" },
  { min: 20, grade: "G", bg: "bg-[#74499b]", text: "text-white" },
  { min: -Infinity, grade: "U", bg: "bg-[#3a3348]", text: "text-white" },
];

export function gradeForPct(pct: number | null | undefined): GradeInfo | null {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return null;
  const clamped = Math.max(0, Math.min(100, pct));
  const match = BOUNDARIES.find((b) => clamped >= b.min);
  if (!match) return null;
  return { grade: match.grade, bg: match.bg, text: match.text };
}
