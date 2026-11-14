import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { keys } from "./api";
import { LangContext, type Lang } from "./i18n";
import { MainButtonHost } from "./telegram/hooks";

export const SALON = {
  name: "Test",
  timezone: "Asia/Bishkek",
  currency: "KGS",
  default_language: "ru",
  slot_step_min: 15,
  max_days_ahead: 30,
  cancel_min_hours: 2,
  reschedule_min_hours: 2,
  contacts: {},
};

export function renderWithProviders(ui: ReactElement, lang: Lang = "ru") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(keys.salon, SALON);
  return render(
    <QueryClientProvider client={client}>
      <LangContext.Provider value={lang}>
        <MemoryRouter>
          <MainButtonHost>{ui}</MainButtonHost>
        </MemoryRouter>
      </LangContext.Provider>
    </QueryClientProvider>,
  );
}
