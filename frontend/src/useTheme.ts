import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark" | "midnight" | "ocean" | "forest" | "paper";

const STORAGE_KEY = "vantage.theme";
export const THEMES: Theme[] = ["system", "light", "dark", "midnight", "ocean", "forest", "paper"];

function readStored(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (THEMES.includes(stored as Theme)) return stored as Theme;
  } catch {
    /* storage unavailable; fall through to the system default */
  }
  return "system";
}

/**
 * Theme preference, persisted per browser.
 *
 * "system" removes the attribute entirely so the CSS falls back to
 * prefers-color-scheme, rather than freezing whichever mode happened to be
 * active when the choice was made.
 */
export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readStored);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* preference just won't persist */
    }
  }, []);

  return [theme, setTheme];
}
