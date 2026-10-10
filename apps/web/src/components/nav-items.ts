import type { IconName } from "@/components/icons";

export const NAV_ITEMS: { href: string; label: string; short: string; icon: IconName }[] = [
  { href: "/dashboard", label: "Нүүр", short: "Нүүр", icon: "home" },
  { href: "/deals", label: "Гэрээнүүд", short: "Гэрээ", icon: "list" },
  { href: "/deals/new", label: "Шинэ гэрээ", short: "Шинэ", icon: "plus" },
  { href: "/notifications", label: "Мэдэгдэл", short: "Мэдэгдэл", icon: "bell" },
  { href: "/profile", label: "Профайл", short: "Профайл", icon: "user" },
];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/deals") return pathname === "/deals" || (pathname.startsWith("/deals/") && pathname !== "/deals/new");
  if (href === "/profile") return pathname === "/profile" || pathname === "/security";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The admin console has its own navigation (separate admin session). */
export function isAdminPath(pathname: string): boolean {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}
