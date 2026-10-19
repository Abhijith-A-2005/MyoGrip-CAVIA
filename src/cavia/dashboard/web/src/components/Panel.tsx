import type { ReactNode } from "react";
import "./Panel.css";

type Props = {
  area: string;
  title?: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
  focused?: boolean;
  dimmed?: boolean;
  className?: string;
  children?: ReactNode;
};

export function Panel({ area, title, subtitle, aside, focused, dimmed, className, children }: Props) {
  return (
    <section
      className={`panel ${className ?? ""}`}
      data-area={area}
      data-focused={focused || undefined}
      data-dimmed={dimmed || undefined}
      aria-label={title}
    >
      {(title || aside) && (
        <header className="panel-head">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          {aside}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}
