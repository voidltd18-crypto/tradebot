import type React from "react";

export type AnyObj = Record<string, any>;
export type Tab = "overview" | "positions" | "reports" | "intelligence" | "portfolio" | "explorer" | "audit" | "weekly" | "observatory" | "crypto" | "admin";
export type Currency = "GBP" | "USD";
export type BuySizeMode = "full" | "partial";
export type ActionFn = (endpoint: string) => Promise<void>;
export type PositionStyleFn = (position: AnyObj) => React.CSSProperties;
