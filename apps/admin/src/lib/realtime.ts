/**
 * Admin WebSocket client: reconnects with exponential backoff + jitter, answers pings,
 * and after every reconnect asks the caller to catch up via the REST feed (no lost events).
 */

export interface RealtimeEvent {
  id: string;
  type: string;
  booking_id: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export type ConnectionState = "connecting" | "open" | "closed";

export interface RealtimeOptions {
  url: string;
  onEvent: (event: RealtimeEvent) => void;
  onState?: (state: ConnectionState) => void;
  /** called after a reconnect (not the first connect) to fetch missed events */
  onReconnect?: () => void;
  socketFactory?: (url: string) => WebSocket;
  random?: () => number;
}

export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1_000 * 2 ** attempt);
  return Math.round(base / 2 + random() * (base / 2));
}

export function connectRealtime(options: RealtimeOptions): () => void {
  const make = options.socketFactory ?? ((url: string) => new WebSocket(url));
  let socket: WebSocket | null = null;
  let attempt = 0;
  let stopped = false;
  let everOpened = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    if (stopped) return;
    options.onState?.("connecting");
    socket = make(options.url);
    socket.onopen = () => {
      if (everOpened) options.onReconnect?.();
      everOpened = true;
      attempt = 0;
      options.onState?.("open");
    };
    socket.onmessage = (message: MessageEvent) => {
      try {
        const data = JSON.parse(String(message.data)) as { type: string; event?: RealtimeEvent };
        if (data.type === "event" && data.event) options.onEvent(data.event);
        else if (data.type === "ping") socket?.send("ping");
      } catch {
        // ignore malformed frames
      }
    };
    socket.onclose = () => {
      options.onState?.("closed");
      if (stopped) return;
      timer = setTimeout(open, backoffDelay(attempt, options.random));
      attempt += 1;
    };
    socket.onerror = () => socket?.close();
  };

  open();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    socket?.close();
  };
}

export function websocketUrl(path: string): string {
  const base = import.meta.env.VITE_API_BASE || window.location.origin;
  const url = new URL(path, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** Short notification sound via WebAudio (no asset to download). */
export function beep(): void {
  try {
    const AudioCtx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    oscillator.connect(gain).connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.35);
    oscillator.onended = () => void ctx.close();
  } catch {
    // autoplay restrictions etc.
  }
}
