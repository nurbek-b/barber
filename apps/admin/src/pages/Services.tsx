import type { components } from "@barber/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { MoneyInput } from "@/components/MoneyInput";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
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
import { keys, pickName, useCategories, useServicesList } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useFormat } from "@/lib/format";

type Service = components["schemas"]["ServiceOut"];

export const serviceSchema = z.object({
  name_ru: z.string().trim().min(1),
  name_ky: z.string().trim().optional(),
  name_en: z.string().trim().optional(),
  category_id: z.string().optional(),
  duration_min: z.coerce.number().int().min(5).max(600),
  base_price: z.number({ invalid_type_error: "invalid" }).int().min(0),
  is_active: z.boolean(),
});
export type ServiceForm = z.infer<typeof serviceSchema>;

function i18nOf(values: ServiceForm): Record<string, string> {
  return Object.fromEntries(
    [
      ["ru", values.name_ru],
      ["ky", values.name_ky],
      ["en", values.name_en],
    ].filter(([, v]) => v),
  ) as Record<string, string>;
}

export default function Services() {
  const { t, i18n } = useTranslation();
  const { money } = useFormat();
  const client = useQueryClient();
  const services = useServicesList();
  const categories = useCategories();
  const [editing, setEditing] = useState<Service | "new" | null>(null);
  const [categoryName, setCategoryName] = useState("");

  const refresh = () => {
    void client.invalidateQueries({ queryKey: keys.services });
    void client.invalidateQueries({ queryKey: keys.categories });
  };
  const addCategory = useMutation({
    mutationFn: () =>
      call(
        api.POST(`${ADMIN}/service-categories`, {
          body: { name_i18n: { ru: categoryName }, sort_order: 0 },
        }),
      ),
    onSuccess: () => {
      setCategoryName("");
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const removeCategory = useMutation({
    mutationFn: (id: string) =>
      call(
        api.DELETE(`${ADMIN}/service-categories/{category_id}`, {
          params: { path: { category_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  const categoryName_ = (id: string | null | undefined) =>
    pickName(categories.data?.find((c) => c.id === id)?.name_i18n, i18n.language);

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("services.title")}
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus /> {t("services.newService")}
          </Button>
        }
      />
      <div className="grid gap-4 xl:grid-cols-4">
        <Card className="xl:col-span-3">
          <CardContent className="pt-5">
            <Table>
              <thead className="border-b">
                <tr>
                  <Th>{t("common.name")}</Th>
                  <Th>{t("services.category")}</Th>
                  <Th>{t("services.duration")}</Th>
                  <Th>{t("services.basePrice")}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {services.data?.map((service) => (
                  <tr
                    key={service.id}
                    className="cursor-pointer border-b hover:bg-muted/50"
                    onClick={() => setEditing(service)}
                  >
                    <Td className="font-medium">{pickName(service.name_i18n, i18n.language)}</Td>
                    <Td>{categoryName_(service.category_id)}</Td>
                    <Td>{t("common.minutes", { n: service.duration_min })}</Td>
                    <Td className="tabular-nums">{money(service.base_price)}</Td>
                    <Td>
                      {!service.is_active && (
                        <Badge variant="secondary">{t("common.inactive")}</Badge>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("services.categories")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {categories.data?.map((category) => (
              <div key={category.id} className="flex items-center justify-between text-sm">
                {pickName(category.name_i18n, i18n.language)}
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("common.delete")}
                  onClick={() => removeCategory.mutate(category.id)}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}
            <div className="flex gap-2">
              <Input
                placeholder={t("services.newCategory")}
                value={categoryName}
                onChange={(e) => setCategoryName(e.target.value)}
              />
              <Button
                size="icon"
                disabled={!categoryName.trim()}
                onClick={() => addCategory.mutate()}
                aria-label={t("common.add")}
              >
                <Plus />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
      {editing && (
        <ServiceDialog
          service={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ServiceDialog({ service, onClose }: { service: Service | null; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const client = useQueryClient();
  const categories = useCategories();
  const form = useForm<ServiceForm>({
    resolver: zodResolver(serviceSchema),
    defaultValues: {
      name_ru: service?.name_i18n.ru ?? "",
      name_ky: service?.name_i18n.ky ?? "",
      name_en: service?.name_i18n.en ?? "",
      category_id: service?.category_id ?? "",
      duration_min: service?.duration_min ?? 30,
      base_price: service?.base_price ?? 0,
      is_active: service?.is_active ?? true,
    },
  });

  const save = useMutation({
    mutationFn: (values: ServiceForm) => {
      const body = {
        name_i18n: i18nOf(values),
        category_id: values.category_id || null,
        duration_min: values.duration_min,
        base_price: values.base_price,
        is_active: values.is_active,
        sort_order: service?.sort_order ?? 0,
        description_i18n: service?.description_i18n ?? {},
      };
      return service
        ? call(
            api.PATCH(`${ADMIN}/services/{service_id}`, {
              params: { path: { service_id: service.id } },
              body,
            }),
          )
        : call(api.POST(`${ADMIN}/services`, { body }));
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      void client.invalidateQueries({ queryKey: keys.services });
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const errors = form.formState.errors;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={service ? t("common.edit") : t("services.newService")}>
        <form
          className="space-y-3"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          noValidate
        >
          <Field
            label={t("services.nameRu")}
            htmlFor="s-ru"
            error={errors.name_ru && t("common.required")}
          >
            <Input id="s-ru" {...form.register("name_ru")} />
          </Field>
          <Field label={t("services.nameKy")} htmlFor="s-ky">
            <Input id="s-ky" {...form.register("name_ky")} />
          </Field>
          <Field label={t("services.nameEn")} htmlFor="s-en">
            <Input id="s-en" {...form.register("name_en")} />
          </Field>
          <Field label={t("services.category")} htmlFor="s-cat">
            <NativeSelect id="s-cat" {...form.register("category_id")}>
              <option value="">—</option>
              {categories.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {pickName(c.name_i18n, i18n.language)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field
              label={t("services.duration")}
              htmlFor="s-dur"
              error={errors.duration_min && "5–600"}
            >
              <Input id="s-dur" type="number" {...form.register("duration_min")} />
            </Field>
            <Field
              label={t("services.basePrice")}
              htmlFor="s-price"
              error={errors.base_price && t("common.required")}
            >
              <Controller
                control={form.control}
                name="base_price"
                render={({ field }) => (
                  <MoneyInput
                    id="s-price"
                    value={field.value ?? null}
                    onChange={(v) => field.onChange(v ?? Number.NaN)}
                  />
                )}
              />
            </Field>
          </div>
          <Controller
            control={form.control}
            name="is_active"
            render={({ field }) => (
              <label className="flex items-center justify-between text-sm">
                {t("common.active")}
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              </label>
            )}
          />
          <div className="flex justify-end">
            <Button type="submit" loading={save.isPending}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
