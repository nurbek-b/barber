import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  onNativeMainButton,
  setNativeBackButton,
  setNativeMainButton,
  telegramEnv,
  type MainButtonState,
} from "./sdk";

/**
 * MainButton: native Telegram button inside Telegram, an in-page fallback elsewhere
 * (dev mock, e2e tests). Screens just call useMainButton(...).
 */
interface FallbackState extends MainButtonState {
  onClick: (() => void) | null;
}

const FallbackContext = createContext<(state: FallbackState | null) => void>(() => undefined);

export function MainButtonHost({ children }: { children: ReactNode }) {
  const [state, setState] = useState<FallbackState | null>(null);
  const native = telegramEnv().native;
  return (
    <FallbackContext.Provider value={setState}>
      {children}
      {!native && state?.visible && (
        <div className="fixed inset-x-0 bottom-0 z-20 bg-bg/95 px-4 pb-[calc(12px+var(--safe-bottom))] pt-3 backdrop-blur">
          <button
            type="button"
            data-testid="main-button"
            disabled={!state.enabled || state.loading}
            onClick={() => state.onClick?.()}
            className="h-12 w-full rounded-xl bg-button font-semibold text-button-text transition active:scale-[0.99] disabled:opacity-50"
          >
            {state.loading ? "…" : state.text}
          </button>
        </div>
      )}
    </FallbackContext.Provider>
  );
}

export function useMainButton(options: {
  text: string;
  visible?: boolean;
  enabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}): void {
  const setFallback = useContext(FallbackContext);
  const handler = useRef(options.onClick);
  handler.current = options.onClick;
  const { text, visible = true, enabled = true, loading = false } = options;

  useEffect(() => {
    const state = { text, visible, enabled, loading };
    setNativeMainButton(state);
    setFallback({ ...state, onClick: () => handler.current() });
  }, [text, visible, enabled, loading, setFallback]);

  useEffect(() => {
    const unsubscribe = onNativeMainButton(() => handler.current());
    return () => {
      unsubscribe();
      setNativeMainButton({ text: "", visible: false, enabled: false, loading: false });
      setFallback(null);
    };
  }, [setFallback]);
}

/** BackButton: navigates back (or calls `onBack`). Pass `false` to hide it. */
export function useBackButton(onBack?: (() => void) | false): void {
  const navigate = useNavigate();
  const handler = useRef<(() => void) | null>(null);
  handler.current = onBack === false ? null : (onBack ?? (() => navigate(-1)));
  const enabled = onBack !== false;

  useEffect(() => {
    if (!enabled) return setNativeBackButton(null);
    return setNativeBackButton(() => handler.current?.());
  }, [enabled]);
}
