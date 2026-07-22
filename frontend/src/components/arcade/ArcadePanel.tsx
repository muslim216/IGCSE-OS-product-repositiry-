import type { ReactNode } from "react";
import PanelHeader, { type ArcadeAccent } from "./PanelHeader";

export default function ArcadePanel({
  title,
  accent = "mint",
  action,
  className = "",
  children,
}: {
  title?: string;
  accent?: ArcadeAccent;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`border-4 border-black bg-arcade-panel shadow-[6px_6px_0px_0px_rgba(0,0,0,1)] ${className}`}
    >
      {title && <PanelHeader title={title} accent={accent} action={action} />}
      <div className="p-4">{children}</div>
    </section>
  );
}
