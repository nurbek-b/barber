import type { components } from "@barber/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Eye, EyeOff, ImagePlus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { FileButton } from "@/components/FileButton";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { keys } from "@/features/queries";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { useFormat } from "@/lib/format";

type Barber = components["schemas"]["BarberDetailOut"];
const MAX_WORKS = 12;

/** The barber's works catalogue (portfolio) shown on their Mini App profile. */
export function WorksTab({ barber, writable }: { barber: Barber; writable: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const refresh = () => void client.invalidateQueries({ queryKey: keys.barbers });
  const onError = (error: unknown) => toast.error(errorMessage(error));
  const path = { barber_id: barber.id };

  const add = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return call(
        api.POST(`${ADMIN}/barbers/{barber_id}/portfolio`, {
          params: { path },
          body: form as never,
          bodySerializer: (body: unknown) => body as FormData,
        }),
      );
    },
    onSuccess: refresh,
    onError,
  });
  const set = useMutation({
    mutationFn: (urls: string[]) =>
      call(api.PUT(`${ADMIN}/barbers/{barber_id}/portfolio`, { params: { path }, body: { urls } })),
    onSuccess: refresh,
    onError,
  });

  const works = barber.portfolio ?? [];
  const move = (index: number, delta: number) => {
    const next = [...works];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item!);
    set.mutate(next);
  };

  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <p className="text-sm text-muted-foreground">
          {t("barbers.worksHint", { max: MAX_WORKS })}
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {works.map((url, index) => (
            <figure key={url} className="overflow-hidden rounded-lg border">
              <img src={url} alt="" className="aspect-square w-full object-cover" />
              {writable && (
                <figcaption className="flex justify-between p-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("settings.moveLeft")}
                    disabled={index === 0 || set.isPending}
                    onClick={() => move(index, -1)}
                  >
                    <ChevronLeft />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("common.delete")}
                    disabled={set.isPending}
                    onClick={() => set.mutate(works.filter((item) => item !== url))}
                  >
                    <Trash2 />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={t("settings.moveRight")}
                    disabled={index === works.length - 1 || set.isPending}
                    onClick={() => move(index, 1)}
                  >
                    <ChevronRight />
                  </Button>
                </figcaption>
              )}
            </figure>
          ))}
        </div>
        {writable && works.length < MAX_WORKS && (
          <FileButton
            accept="image/jpeg,image/png,image/webp"
            variant="outline"
            loading={add.isPending}
            onFile={add.mutate}
          >
            <ImagePlus /> {t("barbers.addWork")}
          </FileButton>
        )}
      </CardContent>
    </Card>
  );
}

/** Reviews of the barber with moderation (hide / show). */
export function ReviewsTab({ barberId }: { barberId: string }) {
  const { t } = useTranslation();
  const can = useCan();
  const { dateTime } = useFormat();
  const client = useQueryClient();
  const key = ["reviews", barberId];
  const reviews = useQuery({
    queryKey: key,
    queryFn: () =>
      call(api.GET(`${ADMIN}/reviews`, { params: { query: { barber_id: barberId, limit: 100 } } })),
  });
  const toggle = useMutation({
    mutationFn: ({ id, hidden }: { id: string; hidden: boolean }) =>
      call(
        api.POST(`${ADMIN}/reviews/{booking_id}/visibility`, {
          params: { path: { booking_id: id } },
          body: { hidden },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: keys.barbers }); // rating changes
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (reviews.isPending) return <Skeleton className="h-40" />;
  if (reviews.isError) return <p className="text-destructive">{errorMessage(reviews.error)}</p>;
  return (
    <Card>
      <CardContent className="space-y-3 pt-5">
        <p className="text-xs text-muted-foreground">{t("barbers.hiddenHint")}</p>
        {reviews.data.items.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("barbers.noReviews")}</p>
        )}
        {reviews.data.items.map((review) => (
          <div
            key={review.booking_id}
            className={`space-y-1 rounded-md border p-3 ${review.hidden ? "opacity-60" : ""}`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-amber-500">
                {"★".repeat(review.rating)}
                <span className="text-muted-foreground/40">{"★".repeat(5 - review.rating)}</span>
              </span>
              <span className="font-medium">{review.client_name || "—"}</span>
              <span className="text-xs text-muted-foreground">{dateTime(review.created_at)}</span>
              {review.hidden && <Badge variant="secondary">{t("barbers.hidden")}</Badge>}
              {can("barbers:write") && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  loading={toggle.isPending && toggle.variables?.id === review.booking_id}
                  onClick={() => toggle.mutate({ id: review.booking_id, hidden: !review.hidden })}
                >
                  {review.hidden ? <Eye /> : <EyeOff />}
                  {review.hidden ? t("barbers.show") : t("barbers.hide")}
                </Button>
              )}
            </div>
            {review.text && <p className="whitespace-pre-line text-sm">{review.text}</p>}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
