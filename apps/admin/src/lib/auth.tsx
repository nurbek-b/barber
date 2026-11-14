import type { AdminMe } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ADMIN, ApiError, api, call, setSessionExpiredHandler } from "./api";

export type Permission =
  | "dashboard:read"
  | "barbers:read"
  | "barbers:read_own"
  | "barbers:write"
  | "services:read"
  | "services:write"
  | "clients:read"
  | "clients:write"
  | "bookings:read"
  | "bookings:read_own"
  | "bookings:write"
  | "bookings:status_own"
  | "finance:read"
  | "finance:export"
  | "settings:read"
  | "settings:write"
  | "bonus:adjust"
  | "bonus_settings:write"
  | "staff:manage"
  | "audit:read"
  | "notifications:read";

interface AuthValue {
  me: AdminMe;
  can: (...perms: Permission[]) => boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);
export const meKey = ["auth", "me"] as const;

export function useMeQuery() {
  return useQuery({
    queryKey: meKey,
    queryFn: () => call(api.GET(`${ADMIN}/auth/me`)),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

export function useCan(): (...perms: Permission[]) => boolean {
  return useAuth().can;
}

/** Renders children only when the user has at least one of `perm`. */
export function Can({ perm, children }: { perm: Permission | Permission[]; children: ReactNode }) {
  const can = useCan();
  const list = Array.isArray(perm) ? perm : [perm];
  return can(...list) ? <>{children}</> : null;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMeQuery();
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();

  useEffect(() => {
    setSessionExpiredHandler(() => {
      client.clear();
      navigate("/login", { replace: true, state: { from: location.pathname } });
    });
  }, [client, navigate, location.pathname]);

  const logout = useMutation({
    mutationFn: () => call(api.POST(`${ADMIN}/auth/logout`)),
    onSettled: () => {
      client.clear();
      navigate("/login", { replace: true });
    },
  });

  if (me.isPending) {
    return <div className="flex h-screen items-center justify-center text-muted-foreground">…</div>;
  }
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) {
      return <Navigate to="/login" replace state={{ from: location.pathname }} />;
    }
    return <div className="p-8 text-destructive">{String(me.error)}</div>;
  }
  const permissions = new Set(me.data.permissions);
  const value: AuthValue = {
    me: me.data,
    can: (...perms) => perms.some((perm) => permissions.has(perm)),
    logout: async () => {
      await logout.mutateAsync().catch(() => undefined);
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Route guard: redirect to the dashboard (or first allowed page) without the permission. */
export function RequirePermission({
  perm,
  children,
}: {
  perm: Permission | Permission[];
  children: ReactNode;
}) {
  const can = useCan();
  const list = Array.isArray(perm) ? perm : [perm];
  if (!can(...list)) return <Navigate to={can("dashboard:read") ? "/" : "/calendar"} replace />;
  return <>{children}</>;
}

export { AuthContext };
