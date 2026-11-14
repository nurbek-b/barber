import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Screen } from "../../components/ui";
import { useT } from "../../i18n";
import { useBooking } from "../../store/booking";
import { useBackButton, useMainButton } from "../../telegram/hooks";

export default function DoneStep() {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const reset = useBooking((state) => state.reset);
  const rescheduled = Boolean((location.state as { rescheduled?: boolean } | null)?.rescheduled);

  useEffect(() => reset(), [reset]);
  useBackButton(false);
  useMainButton({
    text: t("button.myBookings"),
    onClick: () => navigate("/bookings", { replace: true }),
  });

  return (
    <Screen title="" withMainButton>
      <div className="flex flex-col items-center gap-4 pt-16 text-center">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-green-500/15 text-4xl">
          ✓
        </div>
        <h1 className="text-2xl font-semibold" data-testid="done-title">
          {rescheduled ? t("done.rescheduled") : t("done.title")}
        </h1>
        <p className="text-hint">{t("done.reminder")}</p>
        <button
          type="button"
          className="mt-4 text-link"
          onClick={() => navigate("/", { replace: true })}
        >
          {t("button.home")}
        </button>
      </div>
    </Screen>
  );
}
