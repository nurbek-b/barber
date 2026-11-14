import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import "@/lib/i18n";
import { AuthContext, Can, RequirePermission, type Permission } from "@/lib/auth";

import { MoneyInput } from "./MoneyInput";

function withAuth(permissions: Permission[], ui: React.ReactNode, path = "/") {
  const value = {
    me: {
      id: "1",
      login: "a",
      full_name: "A",
      role: "admin",
      branch_id: null,
      barber_id: null,
      language: "ru",
      permissions,
    },
    can: (...perms: Permission[]) => perms.some((p) => permissions.includes(p)),
    logout: vi.fn(),
  } as never;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe("RBAC helpers", () => {
  it("Can hides content without the permission", () => {
    withAuth(
      ["clients:read"],
      <>
        <Can perm="clients:read">
          <span>visible</span>
        </Can>
        <Can perm="staff:manage">
          <span>owner only</span>
        </Can>
        <Can perm={["audit:read", "clients:read"]}>
          <span>any of</span>
        </Can>
      </>,
    );
    expect(screen.getByText("visible")).toBeInTheDocument();
    expect(screen.getByText("any of")).toBeInTheDocument();
    expect(screen.queryByText("owner only")).not.toBeInTheDocument();
  });

  it("RequirePermission redirects", () => {
    withAuth(
      ["bookings:read_own"],
      <Routes>
        <Route
          path="/staff"
          element={
            <RequirePermission perm="staff:manage">
              <span>staff page</span>
            </RequirePermission>
          }
        />
        <Route path="/calendar" element={<span>calendar page</span>} />
      </Routes>,
      "/staff",
    );
    expect(screen.queryByText("staff page")).not.toBeInTheDocument();
    expect(screen.getByText("calendar page")).toBeInTheDocument();
  });
});

function Harness({ onValue }: { onValue: (v: number | null) => void }) {
  const [value, setValue] = useState<number | null>(150_050);
  return (
    <MoneyInput
      aria-label="price"
      value={value}
      onChange={(next) => {
        setValue(next);
        onValue(next);
      }}
    />
  );
}

describe("MoneyInput", () => {
  it("shows major units and reports integer minor units", async () => {
    const onValue = vi.fn();
    render(<Harness onValue={onValue} />);
    const input = screen.getByLabelText("price") as HTMLInputElement;
    expect(input.value).toBe("1500.50");
    await userEvent.clear(input);
    await userEvent.type(input, "1 234,5");
    expect(onValue).toHaveBeenLastCalledWith(123_450);
    await userEvent.type(input, "x");
    expect(onValue).toHaveBeenLastCalledWith(null);
    expect(input).toHaveAttribute("aria-invalid", "true");
  });
});
