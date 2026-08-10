const KEY = "hub-theme";

export function initTheme(): void {
  const saved = localStorage.getItem(KEY);
  const sysDark = matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = saved ?? (sysDark ? "dark" : "light");
}

export function toggleTheme(): string {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem(KEY, next);
  return next;
}

export function currentTheme(): string {
  return document.documentElement.dataset.theme ?? "light";
}
