import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, type ReactNode } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";

import { Layout } from "@/features/Layout";
import { queryClient } from "@/lib/api";
import { RequireAuth, RequirePermission, useCan, type Permission } from "@/lib/auth";
import Login from "@/pages/Login";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const CalendarPage = lazy(() => import("@/pages/Calendar"));
const Bookings = lazy(() => import("@/pages/Bookings"));
const Clients = lazy(() => import("@/pages/Clients"));
const ClientCard = lazy(() => import("@/pages/ClientCard"));
const Barbers = lazy(() => import("@/pages/Barbers"));
const BarberEdit = lazy(() => import("@/pages/BarberEdit"));
const Services = lazy(() => import("@/pages/Services"));
const Finance = lazy(() => import("@/pages/Finance"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const BonusPage = lazy(() => import("@/pages/Bonus"));
const Staff = lazy(() => import("@/pages/Staff"));
const Audit = lazy(() => import("@/pages/Audit"));
const Marketing = lazy(() => import("@/pages/Marketing"));

const guard = (perm: Permission | Permission[], element: ReactNode) => (
  <RequirePermission perm={perm}>{element}</RequirePermission>
);

function Home() {
  const can = useCan();
  return can("dashboard:read") ? <Dashboard /> : <Navigate to="/calendar" replace />;
}

const router = createBrowserRouter(
  [
    { path: "/login", element: <Login /> },
    {
      element: (
        <RequireAuth>
          <Layout />
        </RequireAuth>
      ),
      children: [
        { path: "/", element: <Home /> },
        {
          path: "/calendar",
          element: guard(["bookings:read", "bookings:read_own"], <CalendarPage />),
        },
        { path: "/bookings", element: guard(["bookings:read", "bookings:read_own"], <Bookings />) },
        { path: "/clients", element: guard("clients:read", <Clients />) },
        { path: "/clients/:clientId", element: guard("clients:read", <ClientCard />) },
        { path: "/barbers", element: guard(["barbers:read", "barbers:read_own"], <Barbers />) },
        {
          path: "/barbers/:barberId",
          element: guard(["barbers:read", "barbers:read_own"], <BarberEdit />),
        },
        { path: "/services", element: guard("services:write", <Services />) },
        { path: "/finance", element: guard("finance:read", <Finance />) },
        { path: "/settings", element: guard("settings:read", <SettingsPage />) },
        { path: "/bonus", element: guard("settings:read", <BonusPage />) },
        { path: "/staff", element: guard("staff:manage", <Staff />) },
        { path: "/audit", element: guard("audit:read", <Audit />) },
        { path: "/marketing", element: guard("settings:read", <Marketing />) },
        { path: "*", element: <Navigate to="/" replace /> },
      ],
    },
  ],
  { basename: "/admin" },
);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster richColors position="top-right" closeButton />
    </QueryClientProvider>
  );
}
