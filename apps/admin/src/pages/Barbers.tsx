import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
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
  Skeleton,
} from "@/components/ui";
import { PageHeader } from "@/features/Layout";
import { keys, pickName, useBarbersList } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { Can } from "@/lib/auth";

export default function Barbers() {
  const { t, i18n } = useTranslation();
  const barbers = useBarbersList();
  const [creating, setCreating] = useState(false);

  return (
    <div>
      <PageHeader
        title={t("barbers.title")}
        actions={
          <Can perm="barbers:write">
            <Button onClick={() => setCreating(true)}>
              <Plus /> {t("barbers.new")}
            </Button>
          </Can>
        }
      />
      {barbers.isPending && <Skeleton className="h-40" />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {barbers.data?.map((barber) => (
          <Link key={barber.id} to={`/barbers/${barber.id}`}>
            <Card className="transition hover:border-primary/50">
              <CardContent className="flex items-center gap-4 pt-5">
                {barber.photo_url ? (
                  <img
                    src={barber.photo_url}
                    alt=""
                    className="h-14 w-14 rounded-full object-cover"
                  />
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted text-xl">
                    ✂
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{barber.name}</div>
                  <div className="truncate text-sm text-muted-foreground">
                    {pickName(barber.specialization_i18n, i18n.language)}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {barber.is_active && !barber.has_schedule && (
                      <Badge variant="warning">{t("barbers.noSchedule")}</Badge>
                    )}
                    {!barber.photo_url && <Badge variant="secondary">{t("barbers.noPhoto")}</Badge>}
                    {barber.commission_bp > 0 && (
                      <Badge variant="secondary">
                        {t("barbers.commissionShort", { value: barber.commission_bp / 100 })}
                      </Badge>
                    )}
                    {!barber.is_active && (
                      <Badge variant="destructive">{t("common.inactive")}</Badge>
                    )}
                    {barber.is_active && !barber.is_bookable_online && (
                      <Badge variant="warning">{t("barbers.offline")}</Badge>
                    )}
                    {barber.rating !== null && barber.rating !== undefined && (
                      <Badge variant="secondary">
                        ★ {barber.rating.toFixed(1)} ({barber.rating_count})
                      </Badge>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
      <NewBarberDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function NewBarberDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/barbers`, {
          body: {
            name,
            services: [],
            sort_order: 0,
            commission_bp: 0,
            is_active: true,
            is_bookable_online: true,
          },
        }),
      ),
    onSuccess: (barber) => {
      void client.invalidateQueries({ queryKey: keys.barbers });
      onOpenChange(false);
      navigate(`/barbers/${barber.id}`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("barbers.new")}>
        <Field label={t("common.name")} htmlFor="nb-name">
          <Input id="nb-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="flex justify-end">
          <Button
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t("common.create")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
