import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  Badge,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  Field,
  Input,
  NativeSelect,
  Switch,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { useBarbersList } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Account = components["schemas"]["StaffOut"];
type Role = "owner" | "admin" | "barber";
const staffKey = ["staff"] as const;

export default function Staff() {
  const { t } = useTranslation();
  const { dateTime } = useFormat();
  const { me } = useAuth();
  const client = useQueryClient();
  const barbers = useBarbersList();
  const staff = useQuery({
    queryKey: staffKey,
    queryFn: () => call(api.GET(`${ADMIN}/admin-users`)),
  });
  const [editing, setEditing] = useState<Account | "new" | null>(null);

  const toggle = useMutation({
    mutationFn: (account: Account) =>
      call(
        api.PATCH(`${ADMIN}/admin-users/{account_id}`, {
          params: { path: { account_id: account.id } },
          body: { is_active: !account.is_active },
        }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: staffKey }),
    onError: (error) => toast.error(errorMessage(error)),
  });
  const barberName = (id: string | null | undefined) =>
    barbers.data?.find((b) => b.id === id)?.name ?? "";

  return (
    <div>
      <PageHeader
        title={t("staff.title")}
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus /> {t("staff.new")}
          </Button>
        }
      />
      <Card>
        <CardContent className="pt-5">
          <Table>
            <thead className="border-b">
              <tr>
                <Th>{t("staff.login")}</Th>
                <Th>{t("common.name")}</Th>
                <Th>{t("staff.role")}</Th>
                <Th>{t("staff.barber")}</Th>
                <Th>{t("staff.lastLogin")}</Th>
                <Th>{t("common.active")}</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {staff.data?.map((account) => (
                <tr key={account.id} className="border-b last:border-0">
                  <Td className="font-mono">{account.login}</Td>
                  <Td>{account.full_name}</Td>
                  <Td>
                    <Badge variant={account.role === "owner" ? "default" : "secondary"}>
                      {t(`staff.roles.${account.role}`)}
                    </Badge>
                  </Td>
                  <Td>
                    {barberName(account.barber_id)} {account.telegram_linked && "📱"}
                  </Td>
                  <Td>{account.last_login_at ? dateTime(account.last_login_at) : "—"}</Td>
                  <Td>
                    <Switch
                      checked={account.is_active}
                      disabled={account.id === me.id}
                      onCheckedChange={() => toggle.mutate(account)}
                      aria-label={t("common.active")}
                    />
                  </Td>
                  <Td>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(account)}>
                      {t("common.edit")}
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </CardContent>
      </Card>
      {editing && (
        <AccountDialog
          account={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function AccountDialog({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const barbers = useBarbersList();
  const [login, setLogin] = useState(account?.login ?? "");
  const [fullName, setFullName] = useState(account?.full_name ?? "");
  const [role, setRole] = useState<Role>(account?.role ?? "admin");
  const [barberId, setBarberId] = useState(account?.barber_id ?? "");
  const [password, setPassword] = useState("");

  const save = useMutation({
    mutationFn: () =>
      account
        ? call(
            api.PATCH(`${ADMIN}/admin-users/{account_id}`, {
              params: { path: { account_id: account.id } },
              body: {
                full_name: fullName,
                role,
                barber_id: role === "barber" ? barberId || null : null,
                password: password || null,
              },
            }),
          )
        : call(
            api.POST(`${ADMIN}/admin-users`, {
              body: {
                login,
                password,
                full_name: fullName,
                role,
                barber_id: role === "barber" ? barberId || null : null,
                language: "ru",
              },
            }),
          ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: staffKey });
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const valid =
    (account || (login.length >= 3 && password.length >= 10)) &&
    (!password || password.length >= 10) &&
    (role !== "barber" || barberId);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={account ? account.login : t("staff.new")}>
        {!account && (
          <Field label={t("staff.login")} htmlFor="st-login">
            <Input id="st-login" value={login} onChange={(e) => setLogin(e.target.value)} />
          </Field>
        )}
        <Field label={t("common.name")} htmlFor="st-name">
          <Input id="st-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </Field>
        <Field label={t("staff.role")} htmlFor="st-role">
          <NativeSelect id="st-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(["owner", "admin", "barber"] as const).map((r) => (
              <option key={r} value={r}>
                {t(`staff.roles.${r}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        {role === "barber" && (
          <Field label={t("staff.barber")} htmlFor="st-barber">
            <NativeSelect
              id="st-barber"
              value={barberId}
              onChange={(e) => setBarberId(e.target.value)}
            >
              <option value="">—</option>
              {barbers.data?.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}
        <Field label={account ? t("staff.newPassword") : t("staff.password")} htmlFor="st-pass">
          <Input
            id="st-pass"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <div className="flex justify-end">
          <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>
            {t("common.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
