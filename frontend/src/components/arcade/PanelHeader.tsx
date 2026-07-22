import type { ReactNode } from "react";

export type ArcadeAccent = "mint" | "magenta" | "gold";

const ACCENT_TEXT: Record<ArcadeAccent, string> = {
  mint: "text-arcade-mint",
  magenta: "text-arcade-magenta",
  gold: "text-arcade-gold",
};

export default function PanelHeader({
  title,
  accent = "mint",
  action,
}: {
  title: string;
  accent?: ArcadeAccent;
  action?: ReactNode;
}) {
  return (
    <header className="border-b-4 border-black bg-black/40">
      <div className="flex items-center justify-between gap-2 px-4 py-2">
        <h3 className={`font-mono text-xs font-black uppercase tracking-wider ${ACCENT_TEXT[accent]}`}>
          {`>> ${title}`}
        </h3>
        {action}
      </div>
      <div className={`arcade-trim ${ACCENT_TEXT[accent]}`} aria-hidden="true" />
    </header>
  );
}
