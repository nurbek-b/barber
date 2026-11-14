/**
 * Thin wrapper over @telegram-apps/sdk-react: everything Telegram-specific lives here, so
 * screens stay testable and the app also runs in a plain browser (dev mock, e2e).
 */
import {
  bindMiniAppCssVars,
  bindThemeParamsCssVars,
  bindViewportCssVars,
  disableVerticalSwipes,
  expandViewport,
  hapticFeedbackImpactOccurred,
  hapticFeedbackNotificationOccurred,
  hapticFeedbackSelectionChanged,
  hideBackButton,
  init,
  invokeCustomMethod,
  isTMA,
  miniAppReady,
  mockTelegramEnv,
  mountBackButton,
  mountMainButton,
  mountMiniApp,
  mountSwipeBehavior,
  mountThemeParams,
  mountViewport,
  offBackButtonClick,
  offMainButtonClick,
  onBackButtonClick,
  onMainButtonClick,
  openPopup,
  openTelegramLink,
  requestPhoneAccess,
  retrieveLaunchParams,
  setMainButtonParams,
  shareURL,
  showBackButton,
} from "@telegram-apps/sdk-react";

export interface TelegramEnv {
  /** Real Telegram client: native MainButton/BackButton are visible. */
  native: boolean;
  initDataRaw: string | null;
  startParam: string | null;
  languageCode: string | null;
}

let env: TelegramEnv = { native: false, initDataRaw: null, startParam: null, languageCode: null };

export function telegramEnv(): TelegramEnv {
  return env;
}

const DEV_THEME = {
  bg_color: "#ffffff",
  secondary_bg_color: "#f1f1f4",
  text_color: "#111111",
  hint_color: "#8a8a8f",
  link_color: "#2481cc",
  button_color: "#2481cc",
  button_text_color: "#ffffff",
  section_bg_color: "#ffffff",
  destructive_text_color: "#e53935",
};

function mockOutsideTelegram(): boolean {
  const initData = import.meta.env.VITE_DEV_INIT_DATA as string | undefined;
  if (!initData) return false;
  const params = new URLSearchParams({
    tgWebAppData: initData,
    tgWebAppVersion: "8.0",
    tgWebAppPlatform: "tdesktop",
    tgWebAppThemeParams: JSON.stringify(DEV_THEME),
  });
  mockTelegramEnv(params.toString());
  return true;
}

function safe(fn: { isAvailable(): boolean } & (() => unknown)): void {
  try {
    if (fn.isAvailable()) void fn();
  } catch {
    // feature not supported by this Telegram version
  }
}

/** Initialize the SDK. Returns false when there's neither Telegram nor a dev mock. */
export async function initTelegram(): Promise<boolean> {
  // "simple": launch params are present in the URL — instant, no bridge round-trip
  const native = isTMA("simple");
  if (!native) {
    if (!(import.meta.env.DEV || import.meta.env.MODE === "e2e") || !mockOutsideTelegram()) {
      return false;
    }
  }

  init();
  safe(mountMiniApp);
  safe(mountThemeParams);
  safe(mountBackButton);
  safe(mountMainButton);
  safe(mountSwipeBehavior);
  safe(disableVerticalSwipes);
  // The viewport waits for Telegram's answer: skip it in the mock, never block the UI on it.
  if (native && mountViewport.isAvailable()) {
    const timeout = new Promise((resolve) => setTimeout(resolve, 1500));
    await Promise.race([mountViewport().catch(() => undefined), timeout]);
    safe(bindViewportCssVars);
    safe(expandViewport);
  }
  safe(bindThemeParamsCssVars);
  safe(bindMiniAppCssVars);
  safe(miniAppReady);

  const lp = retrieveLaunchParams();
  env = {
    native,
    initDataRaw: lp.initDataRaw ?? null,
    startParam: lp.startParam ?? null,
    languageCode: lp.initData?.user?.languageCode ?? null,
  };
  return true;
}

// ------------------------------------------------------------------ buttons

export interface MainButtonState {
  text: string;
  visible: boolean;
  enabled: boolean;
  loading: boolean;
}

export function setNativeMainButton(state: MainButtonState): void {
  if (!env.native || !setMainButtonParams.isAvailable()) return;
  setMainButtonParams({
    text: state.text,
    isVisible: state.visible,
    isEnabled: state.enabled && !state.loading,
    isLoaderVisible: state.loading,
  });
}

export function onNativeMainButton(handler: () => void): () => void {
  if (!env.native || !onMainButtonClick.isAvailable()) return () => undefined;
  onMainButtonClick(handler);
  return () => offMainButtonClick(handler);
}

export function setNativeBackButton(handler: (() => void) | null): () => void {
  if (!env.native) return () => undefined;
  if (!handler) {
    if (hideBackButton.isAvailable()) hideBackButton();
    return () => undefined;
  }
  if (showBackButton.isAvailable()) showBackButton();
  if (onBackButtonClick.isAvailable()) onBackButtonClick(handler);
  return () => {
    if (offBackButtonClick.isAvailable()) offBackButtonClick(handler);
  };
}

// ------------------------------------------------------------------ haptics

export const haptic = {
  tap(): void {
    if (hapticFeedbackImpactOccurred.isAvailable()) hapticFeedbackImpactOccurred("light");
  },
  select(): void {
    if (hapticFeedbackSelectionChanged.isAvailable()) hapticFeedbackSelectionChanged();
  },
  success(): void {
    if (hapticFeedbackNotificationOccurred.isAvailable())
      hapticFeedbackNotificationOccurred("success");
  },
  error(): void {
    if (hapticFeedbackNotificationOccurred.isAvailable())
      hapticFeedbackNotificationOccurred("error");
  },
};

// ------------------------------------------------------------------ dialogs & links

export async function confirmDialog(message: string, ok: string, cancel: string): Promise<boolean> {
  if (env.native && openPopup.isAvailable()) {
    const id = await openPopup({
      message,
      buttons: [
        { id: "ok", type: "destructive", text: ok },
        { id: "cancel", type: "default", text: cancel },
      ],
    });
    return id === "ok";
  }
  return window.confirm(message);
}

export function share(url: string, text: string): void {
  if (env.native && shareURL.isAvailable()) {
    shareURL(url, text);
    return;
  }
  if (navigator.share) {
    void navigator.share({ url, text }).catch(() => undefined);
    return;
  }
  void navigator.clipboard?.writeText(url);
}

export function openLink(url: string): void {
  if (env.native && openTelegramLink.isAvailable() && url.startsWith("https://t.me/")) {
    openTelegramLink(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

// ------------------------------------------------------------------ phone

/**
 * Ask Telegram for the user's phone. Returns the *signed* raw contact string
 * (contact=…&auth_date=…&hash=…) that the backend verifies, or null if declined.
 * The bot also receives the contact, so the backend learns the phone either way.
 */
export async function requestSignedContact(): Promise<string | null> {
  if (!env.native) return null;
  const fetchContact = async (): Promise<string | null> => {
    try {
      const raw = await invokeCustomMethod("getRequestedContact", {}, crypto.randomUUID(), {
        timeout: 3000,
      });
      return typeof raw === "string" && raw.includes("hash=") ? raw : null;
    } catch {
      return null;
    }
  };
  const existing = await fetchContact();
  if (existing) return existing;
  if (!requestPhoneAccess.isAvailable()) return null;
  const status = await requestPhoneAccess();
  if (status !== "sent") return null;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const raw = await fetchContact();
    if (raw) return raw;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return null;
}
