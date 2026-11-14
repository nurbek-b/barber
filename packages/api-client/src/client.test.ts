import { describe, expect, it } from "vitest";

import { ApiError, call, createApi, NETWORK_ERROR } from "./index";

function fakeFetch(status: number, body: unknown): typeof fetch {
  return async (input) => {
    const request = input instanceof Request ? input : new Request(String(input));
    return new Response(
      JSON.stringify({ ...((body as object) ?? {}), _auth: request.headers.get("Authorization") }),
      {
        status,
        headers: { "Content-Type": "application/json" },
      },
    );
  };
}

describe("api client", () => {
  it("adds the Mini App authorization header", async () => {
    const api = createApi({
      baseUrl: "https://example.test",
      authorization: () => "tma init",
      fetch: fakeFetch(200, { name: "x" }),
    });
    const data = (await call(api.GET("/api/v1/miniapp/salon"))) as unknown as { _auth: string };
    expect(data._auth).toBe("tma init");
  });

  it("turns the unified error body into ApiError", async () => {
    const api = createApi({
      baseUrl: "https://example.test",
      fetch: fakeFetch(409, {
        error: { code: "slot_conflict", message: "Taken", details: { alternatives: [] } },
      }),
    });
    const error = await call(api.GET("/api/v1/miniapp/salon")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("slot_conflict");
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).details).toEqual({ alternatives: [] });
  });

  it("network failures become ApiError(0)", async () => {
    const api = createApi({
      baseUrl: "https://example.test",
      fetch: async () => {
        throw new TypeError("Failed to fetch");
      },
    });
    const error = (await call(api.GET("/api/v1/miniapp/salon")).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.isNetwork).toBe(true);
    expect(error.code).toBe(NETWORK_ERROR);
  });
});
