import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { useTinPreviewOptional } from "../context/TinPreviewContext";

const defaultClass =
  "font-mono text-teal-700 underline underline-offset-2 hover:text-teal-900";

type Props = {
  tin: string;
  className?: string;
  /** Если задано — показывается вместо БИН (например, короткое название). */
  children?: ReactNode;
};

/**
 * Клик открывает мини-карточку; Ctrl/Cmd/Shift + клик — переход на страницу
 * компании (стандартное поведение ссылки).
 */
export function TinLink({ tin, className, children }: Props) {
  const ctx = useTinPreviewOptional();
  const href = `/company/${encodeURIComponent(tin)}`;
  const cls = className ?? defaultClass;

  if (!ctx) {
    return (
      <Link to={href} className={cls}>
        {children ?? tin}
      </Link>
    );
  }

  return (
    <a
      href={href}
      className={cls}
      onClick={(e) => {
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        ctx.openTinPreview(tin);
      }}
    >
      {children ?? tin}
    </a>
  );
}
