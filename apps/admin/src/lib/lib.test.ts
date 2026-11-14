import { describe, expect, it, vi } from "vitest";

import { overlappingDays } from "@/features/ScheduleEditor";

import { backoffDelay, connectRealtime, realtimeUrl } from "./realtime";
import { fromWallClock, toWallClock, wallDayKey } from "./zoned";

describe("wall clock conversion", () => {
  it("shows instants in the salon timezone regardless of the browser timezone", () => {
    const wall = toWallClock("2026-12-07T06:00:00Z", "Asia/Bishkek");
    expect(wall.getHours()).toBe(12);
    expect(wallDayKey(wall)).toBe("2026-12-07");
    expect(fromWallClock(wall, "Asia/Bishkek").toISOString()).toBe("2026-12-07T06:00:00.000Z");
  });

  it("round-trips across a DST change", () => {
    for (const iso of ["2026-03-29T00:30:00Z", "2026-03-29T01:30:00Z", "2026-10-25T03:30:00Z"]) {
      const wall = toWallClock(iso, "Europe/Berlin");
      expect(fromWallClock(wall, "Europe/Berlin").toISOString()).toBe(new Date(iso).toISOString());
    }
  });
});

describe("schedule overlap mirror", () => {
  it("matches the backend rules", () => {
    expect(
      overlappingDays([
        { weekday: 0, start_time: "10:00", end_time: "14:00" },
        { weekday: 0, start_time: "14:00", end_time: "19:00" },
      ]).size,
    ).toBe(0);
    expect([
      ...overlappingDays([
        { weekday: 0, start_time: "10:00", end_time: "14:00" },
        { weekday: 0, start_time: "13:00", end_time: "19:00" },
      ]),
    ]).toEqual([0]);
    expect(
      overlappingDays([
        { weekday: 0, start_time: "20:00", end_time: "03:00" },
        { weekday: 1, start_time: "02:00", end_time: "10:00" },
      ]).size,
    ).toBe(2);
    expect(
      overlappingDays([
        { weekday: 6, start_time: "22:00", end_time: "03:00" },
        { weekday: 0, start_time: "02:00", end_time: "10:00" },
      ]).size,
    ).toBe(2);
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
}

describe("realtime client", () => {
  it("backoff grows exponentially with jitter and is capped", () => {
    expect(backoffDelay(0, () => 0)).toBe(500);
    expect(backoffDelay(0, () => 1)).toBe(1000);
    expect(backoffDelay(3, () => 1)).toBe(8000);
    expect(backoffDelay(20, () => 1)).toBe(30000);
  });

  it("delivers events, answers pings, reconnects and asks to catch up", () => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    const events: string[] = [];
    const onReconnect = vi.fn();
    const stop = connectRealtime({
      url: "wss://x/ws",
      onEvent: (event) => events.push(event.type),
      onReconnect,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
      random: () => 1,
    });
    const first = FakeSocket.instances[0]!;
    first.onopen?.();
    first.onmessage?.({
      data: JSON.stringify({
        type: "event",
        event: {
          id: "1",
          type: "booking_created",
          booking_id: null,
          payload: {},
          created_at: null,
        },
      }),
    });
    first.onmessage?.({ data: JSON.stringify({ type: "ping" }) });
    first.onmessage?.({ data: "garbage" });
    expect(events).toEqual(["booking_created"]);
    expect(first.sent).toEqual(["ping"]);
    expect(onReconnect).not.toHaveBeenCalled();

    first.onclose?.(); // connection dropped
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    const second = FakeSocket.instances[1]!;
    second.onopen?.();
    expect(onReconnect).toHaveBeenCalledTimes(1);

    stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(2); // no reconnect after stop
    vi.useRealTimers();
  });

  it("fetches a fresh ticket for every connect when VITE_WS_URL is set", async () => {
    let n = 0;
    const resolve = realtimeUrl(
      "/api/v1/admin/ws",
      () => Promise.resolve(`t${++n}`),
      "https://api.example.run.app",
    );
    expect(typeof resolve).toBe("function");
    FakeSocket.instances = [];
    vi.useFakeTimers();
    const stop = connectRealtime({
      url: resolve,
      onEvent: () => undefined,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
      random: () => 1,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeSocket.instances[0]!.url).toBe(
      "wss://api.example.run.app/api/v1/admin/ws?ticket=t1",
    );
    FakeSocket.instances[0]!.onclose?.();
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.instances[1]!.url).toBe(
      "wss://api.example.run.app/api/v1/admin/ws?ticket=t2",
    );
    stop();
    vi.useRealTimers();
    expect(realtimeUrl("/ws", () => Promise.resolve("x"), "")).toMatch(/^ws/);
  });
});
