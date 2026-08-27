import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAccount } from "./useAccount";
import { api } from "./api";

vi.mock("./api", () => ({
  api: { getAccount: vi.fn(), signOut: vi.fn() },
}));

const READY = {
  signed_in: true,
  email: "alice@example.com",
  accounts_available: true,
  durable_storage: true,
  email_delivery: true,
  reason: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useAccount", () => {
  it("reports the signed-in account", async () => {
    vi.mocked(api.getAccount).mockResolvedValue(READY);
    const { result } = renderHook(() => useAccount());

    await waitFor(() => expect(result.current.account.email).toBe("alice@example.com"));
    expect(result.current.loading).toBe(false);
  });

  it("falls back to anonymous when the account lookup fails", async () => {
    // An older backend has no /api/auth/me; the app still works signed out.
    vi.mocked(api.getAccount).mockRejectedValue(new Error("Not Found"));
    const { result } = renderHook(() => useAccount());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.account.signed_in).toBe(false);
    expect(result.current.account.accounts_available).toBe(false);
  });

  it("re-reads the account after signing out", async () => {
    vi.mocked(api.getAccount).mockResolvedValue(READY);
    vi.mocked(api.signOut).mockResolvedValue({ signed_in: false });
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current.account.signed_in).toBe(true));

    vi.mocked(api.getAccount).mockResolvedValue({ ...READY, signed_in: false, email: null });
    await act(async () => {
      await result.current.signOut();
    });

    expect(result.current.account.signed_in).toBe(false);
  });

  it("still re-reads when the sign-out request itself fails", async () => {
    // Otherwise a network blip leaves the UI claiming you are signed in.
    vi.mocked(api.getAccount).mockResolvedValue(READY);
    vi.mocked(api.signOut).mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useAccount());
    await waitFor(() => expect(result.current.account.signed_in).toBe(true));

    await act(async () => {
      await result.current.signOut().catch(() => {});
    });

    expect(api.getAccount).toHaveBeenCalledTimes(2);
  });
});
