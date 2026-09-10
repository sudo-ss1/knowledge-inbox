import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("posts a note and returns the accepted item", async () => {
    const fetchMock = mockFetch(202, { id: "itm_1", type: "note", status: "pending", created_at: "now" });
    vi.stubGlobal("fetch", fetchMock);

    const accepted = await api.ingestNote("hello");

    expect(accepted.id).toBe("itm_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/ingest");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ type: "note", content: "hello" });
  });

  it("turns the error envelope into a typed ApiError", async () => {
    const fetchMock = mockFetch(503, {
      error: { code: "embedder_unavailable", message: "Set OPENAI_API_KEY", request_id: "req_9" },
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.ask("why?")).rejects.toMatchObject({
      code: "embedder_unavailable",
      message: "Set OPENAI_API_KEY",
      requestId: "req_9",
      status: 503,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/query");
    expect(init.method).toBe("POST");
  });

  it("still throws an ApiError when the body is not our envelope", async () => {
    const fetchMock = mockFetch(500, {});
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listItems()).rejects.toBeInstanceOf(ApiError);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/items");
    expect(init?.method).toBeUndefined();
  });

  it("wraps a non-JSON error body in an ApiError instead of a SyntaxError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => "<html><body>502 Bad Gateway</body></html>",
      }),
    );

    await expect(api.listItems()).rejects.toBeInstanceOf(ApiError);
    await expect(api.listItems()).rejects.toMatchObject({
      code: "unreadable_response",
      status: 500,
    });
  });
});
