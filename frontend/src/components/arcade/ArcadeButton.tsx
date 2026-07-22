import type { ReactNode, MouseEventHandler } from "react";
import { Link } from "react-router-dom";

export type ArcadeButtonColor = "mint" | "magenta" | "gold" | "dark";

const COLOR_CLASSES: Record<ArcadeButtonColor, string> = {
  mint: "bg-arcade-mint text-[#050308]",
  magenta: "bg-arcade-magenta text-white",
  gold: "bg-arcade-gold text-[#050308]",
  dark: "bg-arcade-panel-2 text-arcade-mint",
};

const SIZE_CLASSES = {
  md: "px-4 py-2 text-xs",
  lg: "px-5 py-3 text-sm",
};

const BASE =
  "inline-flex items-center justify-center gap-2 border-4 border-black font-mono font-black uppercase tracking-wider shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] transition-[transform,box-shadow] duration-100 hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none disabled:opacity-50 disabled:pointer-events-none";

export default function ArcadeButton({
  to,
  onClick,
  color = "mint",
  size = "md",
  className = "",
  disabled,
  children,
}: {
  to?: string;
  onClick?: MouseEventHandler;
  color?: ArcadeButtonColor;
  size?: "md" | "lg";
  className?: string;
  disabled?: boolean;
  children: ReactNode;
}) {
  const classes = `${BASE} ${COLOR_CLASSES[color]} ${SIZE_CLASSES[size]} ${className}`;

  if (to) {
    return (
      <Link to={to} className={classes}>
        {children}
      </Link>
    );
  }

  return (
    <button type="button" onClick={onClick} disabled={disabled} className={classes}>
      {children}
    </button>
  );
}
