import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, type ReactNode } from "react";
import {
  createMemoryRouter,
  NavLink,
  Outlet,
  RouterProvider,
  type RouteObject,
} from "react-router-dom";

import { queryClient, track, useMe } from "./api";
import { useBrandTheme } from "./brand";
import { OfflineBanner, SkeletonList } from "./components/ui";
import { LangContext, normalizeLang, useT } from "./i18n";
import Home from "./pages/Home";
import { pathForStartParam } from "./deeplinks";
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
const BarberProfile = lazy(() => import("./pages/BarberProfile"));
const ReviewForm = lazy(() => import("./pages/ReviewForm"));
const Payment = lazy(() => import("./pages/Payment"));
const Shop = lazy(() => import("./pages/Shop"));
const Order = lazy(() => import("./pages/Order"));

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

const TAB_ICONS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  bookings:
    "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  bonus:
    "M20 12v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8m16 0H4m16 0V8H4v4m8-4v13m0-13S10.5 3 8 3.5 7 7 8.5 8M12 8s1.5-5 4-4.5S17 7 15.5 8",
  shop: "M6 7h12l1 13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1zm3 0a3 3 0 0 1 6 0",
} as const;

function TabIcon({ name }: { name: keyof typeof TAB_ICONS }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-6 w-6"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={TAB_ICONS[name]} />
    </svg>
  );
}

function TabBar() {
  const t = useT();
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors active:opacity-60 ${
      isActive ? "text-link" : "text-hint"
    }`;
  const item = (to: string, icon: keyof typeof TAB_ICONS, label: string) => (
    <NavLink to={to} end={to === "/"} className={tab}>
      {({ isActive }) => (
        <>
          <span
            className={`flex h-7 w-12 items-center justify-center rounded-full transition-colors ${
              isActive ? "bg-button/15" : ""
            }`}
          >
            <TabIcon name={icon} />
          </span>
          {label}
        </>
      )}
    </NavLink>
  );
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 flex border-t border-separator bg-bg/95 pb-[var(--safe-bottom)] backdrop-blur">
      {item("/", "home", t("nav.home"))}
      {item("/bookings", "bookings", t("nav.bookings"))}
      {item("/bonus", "bonus", t("nav.bonus"))}
      {item("/shop", "shop", t("nav.shop"))}
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
      {
        path: "/shop",
        element: (
          <Lazy>
            <Shop />
          </Lazy>
        ),
      },
    ],
  },
  {
    element: <Shell tabs={false} />,
    children: [
      {
        path: "/barber/:barberId",
        element: (
          <Lazy>
            <BarberProfile />
          </Lazy>
        ),
      },
      {
        path: "/review/:bookingId",
        element: (
          <Lazy>
            <ReviewForm />
          </Lazy>
        ),
      },
      {
        path: "/pay/:bookingId",
        element: (
          <Lazy>
            <Payment />
          </Lazy>
        ),
      },
      {
        path: "/order/:orderId",
        element: (
          <Lazy>
            <Order />
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
  // WebApp buttons carry ?startapp=... in the URL instead of Telegram's start_param
  const fromUrl = new URLSearchParams(window.location.search).get("startapp");
  return pathForStartParam(telegramEnv().startParam ?? fromUrl);
}

function Localized({ children }: { children: ReactNode }) {
  useBrandTheme();
  const me = useMe();
  const lang = normalizeLang(me.data?.language ?? telegramEnv().languageCode);
  return <LangContext.Provider value={lang}>{children}</LangContext.Provider>;
}

export default function App() {
  useEffect(() => track("open"), []);
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
