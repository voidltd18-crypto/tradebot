import type React from "react";

export function Card({ title, children, wide = false, className = "" }: { title?: string; children: React.ReactNode; wide?: boolean; className?: string }) {
  return <section className={`card ${wide ? "wide" : ""} ${className}`.trim()}>{title && <h2>{title}</h2>}{children}</section>;
}
