import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Eye, ScrollText, ShieldCheck } from "lucide-react";
import { AvoraGrain, AvoraLockup, SectionOrnament } from "../components/brand";
import { useDocumentTitle } from "../components/page";

/**
 * The frame for every sign-in and sign-up screen. On wide screens a quiet
 * espresso panel beside the form says what avora stands for; on a phone the
 * form is the whole page. One layout, so signing in, creating an account and
 * accepting an invite all feel like the same product.
 */
export function AuthLayout({
  title,
  documentTitle,
  subtitle,
  children,
  footer,
}: {
  title: ReactNode;
  documentTitle: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useDocumentTitle(documentTitle);
  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1fr_minmax(0,34rem)]">
      <AvoraGrain />
      <div className="flex flex-col px-6 py-6 sm:px-10">
        <Link to="/" aria-label="avora home" className="self-start">
          <AvoraLockup />
        </Link>
        <main className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-sm">
            <h1 className="text-[1.75rem] leading-tight text-ink-900">{title}</h1>
            {subtitle && <p className="mt-2 text-[15px] text-ink-500">{subtitle}</p>}
            <div className="mt-8">{children}</div>
            {footer && <div className="mt-6 text-sm text-ink-500">{footer}</div>}
          </div>
        </main>
        <p className="text-center text-xs text-ink-500">
          <Link to="/privacy" className="hover:text-ink-900 hover:underline">
            Privacy policy
          </Link>
        </p>
      </div>
      <aside className="avora-espresso hidden flex-col justify-center px-12 lg:flex">
        <SectionOrnament className="max-w-[10rem]" />
        <p className="mt-8 font-display text-3xl leading-snug text-surface">
          The AI drafts. The tutor decides.
        </p>
        <ul className="mt-8 space-y-4 text-sm text-line">
          <li className="flex gap-3">
            <ScrollText aria-hidden className="h-5 w-5 shrink-0 text-brand-500" />
            Every answer marked against the mark scheme.
          </li>
          <li className="flex gap-3">
            <Eye aria-hidden className="h-5 w-5 shrink-0 text-brand-500" />
            Uncertain marks wait for the tutor, never guessed.
          </li>
          <li className="flex gap-3">
            <ShieldCheck aria-hidden className="h-5 w-5 shrink-0 text-brand-500" />
            Each tutor's students, kept separate and private.
          </li>
        </ul>
      </aside>
    </div>
  );
}

/** Small "or do this instead" line under a form. */
export function AuthAlt({ children }: { children: ReactNode }) {
  return <p className="leading-relaxed">{children}</p>;
}

export const authLink = "font-medium text-brand-600 hover:text-brand-700 hover:underline";
