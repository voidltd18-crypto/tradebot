import type React from "react";

export function Stat({ label, value, sub, className = "" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return <section className="card stat"><span>{label}</span><strong className={className}>{value}</strong>{sub && <small>{sub}</small>}</section>;
}
