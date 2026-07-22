import { Link } from "react-router-dom";
import GradeBadge from "./GradeBadge";
import ArcadeEmpty from "./ArcadeEmpty";

export interface HighScoreRow {
  rank: number;
  name: string;
  detail?: string;
  pct: number;
  to?: string;
}

function Row({ row }: { row: HighScoreRow }) {
  const rankColor = row.rank <= 3 ? "text-arcade-gold" : "text-slate-300";
  const content = (
    <div className="flex items-center gap-3 border-b-2 border-black py-2 last:border-b-0">
      <span className={`w-8 shrink-0 font-mono text-sm font-black ${rankColor}`}>
        {String(row.rank).padStart(2, "0")}.
      </span>
      <span className="truncate font-mono text-sm font-black uppercase text-slate-100">{row.name}</span>
      {row.detail && (
        <span className="shrink-0 truncate font-mono text-xs text-slate-500">{row.detail}</span>
      )}
      <span className="flex-1 border-b-2 border-dotted border-white/20" aria-hidden="true" />
      <span className="shrink-0 font-mono text-xs font-black text-arcade-gold">
        PTS {String(Math.round(row.pct)).padStart(3, "0")}
      </span>
      <GradeBadge pct={row.pct} size="sm" />
    </div>
  );

  if (row.to) {
    return (
      <Link to={row.to} className="block hover:bg-white/5">
        {content}
      </Link>
    );
  }
  return content;
}

export default function HighScoreTable({ rows }: { rows: HighScoreRow[] }) {
  if (rows.length === 0) {
    return <ArcadeEmpty text="NO SCORES YET" />;
  }

  return (
    <div className="flex flex-col">
      {rows.map((row) => (
        <Row key={`${row.rank}-${row.name}`} row={row} />
      ))}
    </div>
  );
}
