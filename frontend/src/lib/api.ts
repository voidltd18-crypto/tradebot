import type { AnyObj } from "./types";

export const API_URL = import.meta.env.VITE_API_BASE || "https://tradebot-0myo.onrender.com";
export const BOT_VERSION = "V18.2.12 DB Hot-Path Cleanup";

export async function readJson(res: Response): Promise<AnyObj> {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { message: text };
  }
}
