import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmt(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(digits);
}
