import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useMemo, type ReactNode } from "react";
import {
  createMemoryRouter,
  NavLink,
  Outlet,
  RouterProvider,
  type RouteObject,
} from "react-router-dom";

import { queryClient, useMe } from "./api";
import { OfflineBanner, SkeletonList } from "./components/ui";
import { LangContext, normalizeLang, useT } from "./i18n";
import Home from "./pages/Home";
import { telegramEnv } from "./telegram/sdk";
import { MainButtonHost } from "./telegram/hooks";

// Each step is its own chunk: the first screen (Home) ships only what it needs.
const BarberStep = lazy(() => import("./pages/booking/BarberStep"));
const ServicesStep = lazy(() => import("./pages/booking/ServicesStep"));
const TimeStep = lazy(() => import("./pages/booking/TimeStep"));
const ConfirmStep = lazy(() => import("./pages/booking/ConfirmStep"));
const DoneStep = lazy(() => import("./pages/booking/DoneStep"));
const MyBookings = lazy(() => import("./pages/MyBookings"));
const Bonus = lazy(() => import("./pages/Bonus"));

function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="p-4">
          <SkeletonList rows={4} />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function TabBar() {
  const t = useT();
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex flex-1 flex-col items-center py-2 text-xs ${isActive ? "text-button" : "text-hint"}`;
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-separator bg-bg/95 pb-[var(--safe-bottom)] backdrop-blur">
      <NavLink to="/" end className={tab}>
        <span className="text-lg">⌂</span>
        {t("nav.home")}
      </NavLink>
      <NavLink to="/bookings" className={tab}>
        <span className="text-lg">☰</span>
        {t("nav.bookings")}
      </NavLink>
      <NavLink to="/bonus" className={tab}>
        <span className="text-lg">★</span>
        {t("nav.bonus")}
      </NavLink>
    </nav>
  );
}

function Shell({ tabs }: { tabs: boolean }) {
  return (
    <>
      <OfflineBanner />
      <Outlet />
      {tabs && <TabBar />}
    </>
  );
}

export const routes: RouteObject[] = [
  {
    element: <Shell tabs />,
    children: [
      { path: "/", element: <Home /> },
      {
        path: "/bookings",
        element: (
          <Lazy>
            <MyBookings />
          </Lazy>
        ),
      },
      {
        path: "/bonus",
        element: (
          <Lazy>
            <Bonus />
          </Lazy>
        ),
      },
    ],
  },
  {
    path: "/book",
    element: <Shell tabs={false} />,
    children: [
      {
        path: "barber",
        element: (
          <Lazy>
            <BarberStep />
          </Lazy>
        ),
      },
      {
        path: "services",
        element: (
          <Lazy>
            <ServicesStep />
          </Lazy>
        ),
      },
      {
        path: "time",
        element: (
          <Lazy>
            <TimeStep />
          </Lazy>
        ),
      },
      {
        path: "confirm",
        element: (
          <Lazy>
            <ConfirmStep />
          </Lazy>
        ),
      },
      {
        path: "done",
        element: (
          <Lazy>
            <DoneStep />
          </Lazy>
        ),
      },
    ],
  },
];

function initialPath(): string {
  // deep links: startapp=book → open the flow; the referral payload is handled by the backend
  return telegramEnv().startParam === "book" ? "/book/barber" : "/";
}

function Localized({ children }: { children: ReactNode }) {
  const me = useMe();
  const lang = normalizeLang(me.data?.language ?? telegramEnv().languageCode);
  return <LangContext.Provider value={lang}>{children}</LangContext.Provider>;
}

export default function App() {
  // memory router: the Telegram launch params live in the URL hash, don't touch it
  const router = useMemo(() => createMemoryRouter(routes, { initialEntries: [initialPath()] }), []);
  return (
    <QueryClientProvider client={queryClient}>
      <Localized>
        <MainButtonHost>
          <RouterProvider router={router} />
        </MainButtonHost>
      </Localized>
    </QueryClientProvider>
  );
}
