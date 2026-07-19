import { Fragment, type ReactNode } from "react";

/** Renders inline **bold** within a line. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/**
 * Minimal Markdown renderer for AI-generated reports: headings, bullet lists,
 * bold, and paragraphs. Deliberately small — no external dependency.
 */
export function Markdown({ content }: { content: string }) {
  const blocks: ReactNode[] = [];
  const lines = content.split("\n");
  let list: string[] = [];
  let key = 0;

  const flushList = () => {
    if (list.length) {
      blocks.push(
        <ul key={key++} className="my-2 ml-5 list-disc space-y-1">
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^#{1,6}\s/.test(line)) {
      flushList();
      const level = line.match(/^#+/)![0].length;
      const text = line.replace(/^#+\s/, "");
      const cls =
        level <= 1
          ? "mt-1 mb-2 text-xl font-semibold text-slate-800"
          : level === 2
            ? "mt-4 mb-1.5 text-lg font-semibold text-slate-800"
            : "mt-3 mb-1 font-medium text-slate-700";
      blocks.push(
        <p key={key++} className={cls}>
          {inline(text)}
        </p>,
      );
    } else if (/^[-*]\s/.test(line)) {
      list.push(line.replace(/^[-*]\s/, ""));
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      blocks.push(
        <p key={key++} className="my-2 text-sm leading-relaxed text-slate-700">
          {inline(line)}
        </p>,
      );
    }
  }
  flushList();
  return <div>{blocks}</div>;
}
