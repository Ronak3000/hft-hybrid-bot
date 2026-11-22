import type { ReactNode } from 'react';
import s from './lab.module.css';

export function ProjectMasthead({ index, label, title, description, children }: {
  index: string;
  label: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <header className={s.masthead}>
      <div className={s.mastheadInner}>
        <span className={s.kicker}>Market Lab / {label}</span>
        <h1 className={s.title}>{title}</h1>
        <p className={s.intro}>{description}</p>
        <div className={s.tags}>{children}</div>
      </div>
      <span className={s.projectIndex} aria-hidden="true">{index}</span>
    </header>
  );
}
