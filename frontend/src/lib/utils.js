import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * shadcn `cn` — koşullu className birleştir + Tailwind çakışmalarını çöz.
 * @param {...any} inputs
 * @returns {string}
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
