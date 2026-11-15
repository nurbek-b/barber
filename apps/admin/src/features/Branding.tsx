import type { components } from "@barber/api-client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ImagePlus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { FileButton } from "@/components/FileButton";
import { Button, Card, CardContent } from "@/components/ui";
import { ADMIN, api, call, errorMessage } from "@/lib/api";
import { salonKey } from "@/lib/format";

type Salon = components["schemas"]["SalonSettingsOut"];
const IMAGES = "image/jpeg,image/png,image/webp";
const MAX_GALLERY = 8;

function formOf(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}
const multipart = { bodySerializer: (body: unknown) => body as FormData };

/** Logo and salon photos shown on the Mini App home screen. */
export function BrandingCard({ salon, writable }: { salon: Salon; writable: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const onSuccess = (data: Salon) => client.setQueryData(salonKey, data);
  const onError = (error: unknown) => toast.error(errorMessage(error));

  const logo = useMutation({
    mutationFn: (file: File) =>
      call(api.POST(`${ADMIN}/settings/salon/logo`, { body: formOf(file) as never, ...multipart })),
    onSuccess,
    onError,
  });
  const removeLogo = useMutation({
    mutationFn: () => call(api.DELETE(`${ADMIN}/settings/salon/logo`)),
    onSuccess,
    onError,
  });
  const addPhoto = useMutation({
    mutationFn: (file: File) =>
      call(
        api.POST(`${ADMIN}/settings/salon/gallery`, { body: formOf(file) as never, ...multipart }),
      ),
    onSuccess,
    onError,
  });
  const setGallery = useMutation({
    mutationFn: (urls: string[]) =>
      call(api.PUT(`${ADMIN}/settings/salon/gallery`, { body: { urls } })),
    onSuccess,
    onError,
  });

  const gallery = salon.gallery;
  const move = (index: number, delta: number) => {
    const next = [...gallery];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item!);
    setGallery.mutate(next);
  };

  return (
    <Card>
      <CardContent className="space-y-6 pt-5">
        <p className="text-sm text-muted-foreground">{t("settings.brandingHint")}</p>

        <section className="space-y-2">
          <h3 className="font-medium">{t("settings.logo")}</h3>
          <div className="flex flex-wrap items-center gap-4">
            {salon.logo_url ? (
              <img
                src={salon.logo_url}
                alt={t("settings.logo")}
                className="h-20 w-20 rounded-xl border object-contain p-1"
              />
            ) : (
              <div className="flex h-20 w-20 items-center justify-center rounded-xl border border-dashed text-muted-foreground">
                <ImagePlus className="h-6 w-6" />
              </div>
            )}
            {writable && (
              <div className="flex flex-wrap gap-2">
                <FileButton accept={IMAGES} loading={logo.isPending} onFile={logo.mutate}>
                  <ImagePlus /> {t("settings.uploadLogo")}
                </FileButton>
                {salon.logo_url && (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={removeLogo.isPending}
                    onClick={() => removeLogo.mutate()}
                  >
                    <Trash2 /> {t("settings.removeLogo")}
                  </Button>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="space-y-2">
          <h3 className="font-medium">{t("settings.gallery")}</h3>
          <p className="text-xs text-muted-foreground">
            {t("settings.galleryHint", { max: MAX_GALLERY })}
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {gallery.map((url, index) => (
              <figure key={url} className="overflow-hidden rounded-lg border">
                <img src={url} alt="" className="aspect-[4/3] w-full object-cover" />
                {writable && (
                  <figcaption className="flex justify-between gap-1 p-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("settings.moveLeft")}
                      disabled={index === 0 || setGallery.isPending}
                      onClick={() => move(index, -1)}
                    >
                      <ChevronLeft />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("common.delete")}
                      disabled={setGallery.isPending}
                      onClick={() => setGallery.mutate(gallery.filter((item) => item !== url))}
                    >
                      <Trash2 />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={t("settings.moveRight")}
                      disabled={index === gallery.length - 1 || setGallery.isPending}
                      onClick={() => move(index, 1)}
                    >
                      <ChevronRight />
                    </Button>
                  </figcaption>
                )}
              </figure>
            ))}
          </div>
          {writable && gallery.length < MAX_GALLERY && (
            <FileButton
              accept={IMAGES}
              variant="outline"
              loading={addPhoto.isPending}
              onFile={addPhoto.mutate}
            >
              <ImagePlus /> {t("settings.addPhoto")}
            </FileButton>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
