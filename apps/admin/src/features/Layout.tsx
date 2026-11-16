import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  Megaphone,
  BarChart3,
  CalendarDays,
  ClipboardList,
  Coins,
  Gift,
  LayoutDashboard,
  Menu as MenuIcon,
  Moon,
  Scissors,
  Settings,
  Shield,
  Sun,
  UserCog,
  Users,
} from "lucide-react";
import { Suspense, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { Button, Skeleton } from "@/components/ui";
import { useAuth, type Permission } from "@/lib/auth";
import { LANGUAGES, setLanguage } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

import { NotificationsBell, useRealtime } from "./notifications";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  perm: Permission[];
}

const NAV: NavItem[] = [
  { to: "/", label: "nav.dashboard", icon: LayoutDashboard, perm: ["dashboard:read"] },
  {
    to: "/calendar",
    label: "nav.calendar",
    icon: CalendarDays,
    perm: ["bookings:read", "bookings:read_own"],
  },
  {
    to: "/bookings",
    label: "nav.bookings",
    icon: ClipboardList,
    perm: ["bookings:read", "bookings:read_own"],
  },
  { to: "/clients", label: "nav.clients", icon: Users, perm: ["clients:read"] },
  {
    to: "/barbers",
    label: "nav.barbers",
    icon: Scissors,
    perm: ["barbers:read", "barbers:read_own"],
  },
  { to: "/services", label: "nav.services", icon: Coins, perm: ["services:write"] },
  { to: "/finance", label: "nav.finance", icon: BarChart3, perm: ["finance:read"] },
  { to: "/bonus", label: "nav.bonus", icon: Gift, perm: ["settings:read"] },
  { to: "/marketing", label: "nav.marketing", icon: Megaphone, perm: ["settings:read"] },
  { to: "/settings", label: "nav.settings", icon: Settings, perm: ["settings:read"] },
  { to: "/staff", label: "nav.staff", icon: UserCog, perm: ["staff:manage"] },
  { to: "/audit", label: "nav.audit", icon: Shield, perm: ["audit:read"] },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  return (
    <nav className="flex flex-col gap-1 p-3">
      <div className="mb-4 px-3 text-lg font-semibold">✂️ {t("app.title")}</div>
      {NAV.filter((item) => can(...item.perm)).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
              isActive && "bg-accent font-medium text-foreground",
              !isActive && "text-muted-foreground",
            )
          }
        >
          <item.icon className="h-4 w-4" />
          {t(item.label)}
        </NavLink>
      ))}
    </nav>
  );
}

export function Layout() {
  const { t, i18n } = useTranslation();
  const { me, logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const connection = useRealtime();

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r bg-card md:block">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setMobileOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside
            className="absolute inset-y-0 left-0 w-64 bg-card shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="menu"
          >
            <MenuIcon />
          </Button>
          <div className="flex-1" />
          <NotificationsBell connection={connection} />
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={t("common.theme")}>
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
          <Menu.Root>
            <Menu.Trigger asChild>
              <Button variant="outline" size="sm">
                {me.full_name || me.login}
              </Button>
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Content
                align="end"
                sideOffset={6}
                className="z-50 min-w-44 rounded-md border bg-popover p-1 text-sm shadow-md"
              >
                <Menu.Label className="px-2 py-1.5 text-xs text-muted-foreground">
                  {t(`staff.roles.${me.role}`)}
                </Menu.Label>
                <Menu.Separator className="my-1 h-px bg-border" />
                {LANGUAGES.map((lang) => (
                  <Menu.Item
                    key={lang.code}
                    onSelect={() => setLanguage(lang.code)}
                    className={cn(
                      "cursor-pointer rounded px-2 py-1.5 outline-none hover:bg-accent",
                      i18n.language === lang.code && "font-medium",
                    )}
                  >
                    {lang.label}
                  </Menu.Item>
                ))}
                <Menu.Separator className="my-1 h-px bg-border" />
                <Menu.Item
                  onSelect={() => void logout()}
                  className="cursor-pointer rounded px-2 py-1.5 text-destructive outline-none hover:bg-accent"
                >
                  {t("common.logout")}
                </Menu.Item>
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
