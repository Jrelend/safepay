/**
 * Theme preference: "system" follows the OS (prefers-color-scheme); "light" or
 * "dark" set data-theme on <html>. Stored per browser only — a convenience,
 * never account state. THEME_BOOTSTRAP runs before paint (see layout.tsx).
 */
export type ThemePreference = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "safepay-theme";

export const THEME_BOOTSTRAP = `try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export function readTheme(): ThemePreference {
  try {
    const t = localStorage.getItem(THEME_STORAGE_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: ThemePreference): void {
  try {
    if (theme === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage blocked: still apply for this page view */
  }
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}
