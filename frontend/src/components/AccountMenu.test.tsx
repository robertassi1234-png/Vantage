import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountMenu } from "./AccountMenu";
import { api } from "../api";
import type { Account } from "../types";

vi.mock("../api", () => ({
  api: {
    getAccount: vi.fn(),
    requestSignInLink: vi.fn(),
    verifySignIn: vi.fn(),
    signOut: vi.fn(),
  },
}));

const account = (over: Partial<Account> = {}): Account => ({
  signed_in: false,
  email: null,
  accounts_available: true,
  durable_storage: true,
  email_delivery: true,
  reason: null,
  ...over,
});

const signedIn = (over: Partial<Account> = {}) =>
  account({ signed_in: true, email: "alice@example.com", ...over });

function setup(props: Partial<React.ComponentProps<typeof AccountMenu>> = {}) {
  return render(
    <AccountMenu
      account={account()}
      onSignedIn={vi.fn()}
      onSignOut={vi.fn()}
      {...props}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AccountMenu", () => {
  it("offers sign-in when nobody is signed in", () => {
    setup();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows the address once signed in", () => {
    setup({ account: signedIn() });
    expect(screen.getByRole("button", { name: /alice@example.com/i })).toBeInTheDocument();
  });

  it("asks only for an email, never a password", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByPlaceholderText(/you@example.com/i)).toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });

  it("requests a link and reports where it went", async () => {
    const user = userEvent.setup();
    vi.mocked(api.requestSignInLink).mockResolvedValue({
      sent: true,
      message: "Check alice@example.com for your sign-in link.",
    });

    setup();
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await user.type(screen.getByPlaceholderText(/you@example.com/i), "alice@example.com");
    await user.click(screen.getByRole("button", { name: /email me a link/i }));

    expect(api.requestSignInLink).toHaveBeenCalledWith("alice@example.com");
    expect(await screen.findByText(/check alice@example.com/i)).toBeInTheDocument();
  });

  it("surfaces a rejected address instead of pretending it sent", async () => {
    const user = userEvent.setup();
    vi.mocked(api.requestSignInLink).mockRejectedValue(new Error("Too many sign-in links"));

    setup();
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await user.type(screen.getByPlaceholderText(/you@example.com/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /email me a link/i }));

    expect(await screen.findByText(/too many sign-in links/i)).toBeInTheDocument();
  });

  it("will not submit an empty address", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByRole("button", { name: /email me a link/i })).toBeDisabled();
  });

  it("says plainly when the server is not set up for accounts", async () => {
    const user = userEvent.setup();
    setup({
      account: account({
        accounts_available: false,
        reason: "This server is using temporary storage.",
      }),
    });
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByText(/temporary storage/i)).toBeInTheDocument();
  });

  it("warns that alerts cannot be emailed when mail is unconfigured", async () => {
    const user = userEvent.setup();
    setup({ account: signedIn({ email_delivery: false }) });
    await user.click(screen.getByRole("button", { name: /alice@example.com/i }));

    expect(screen.getByText(/can't send email yet/i)).toBeInTheDocument();
  });

  it("signs out through the parent so the whole app refreshes", async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn();
    setup({ account: signedIn(), onSignOut });

    await user.click(screen.getByRole("button", { name: /alice@example.com/i }));
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    expect(onSignOut).toHaveBeenCalled();
  });
});

describe("redeeming a link", () => {
  it("verifies a token from the address bar", async () => {
    vi.mocked(api.verifySignIn).mockResolvedValue({
      signed_in: true,
      email: "alice@example.com",
      claimed: { watchlist: 0, alerts: 0 },
    });

    setup({ pendingToken: "tok123", onTokenHandled: vi.fn() });

    await waitFor(() => expect(api.verifySignIn).toHaveBeenCalledWith("tok123"));
    expect(await screen.findByText(/^signed in\.$/i)).toBeInTheDocument();
  });

  it("says what was carried over from the browser", async () => {
    vi.mocked(api.verifySignIn).mockResolvedValue({
      signed_in: true,
      email: "alice@example.com",
      claimed: { watchlist: 3, alerts: 1 },
    });

    setup({ pendingToken: "tok123" });

    expect(await screen.findByText(/4 saved items moved into your account/i)).toBeInTheDocument();
  });

  it("explains a dead link rather than failing silently", async () => {
    vi.mocked(api.verifySignIn).mockRejectedValue(
      new Error("That sign-in link has already been used or is no longer valid."),
    );

    setup({ pendingToken: "stale" });

    expect(await screen.findByText(/no longer valid/i)).toBeInTheDocument();
  });

  it("tells the parent to clear the token so it cannot be reused", async () => {
    const onTokenHandled = vi.fn();
    vi.mocked(api.verifySignIn).mockResolvedValue({
      signed_in: true,
      email: "alice@example.com",
      claimed: { watchlist: 0, alerts: 0 },
    });

    setup({ pendingToken: "tok123", onTokenHandled });

    await waitFor(() => expect(onTokenHandled).toHaveBeenCalled());
  });

  it("does nothing when there is no token", async () => {
    setup({ pendingToken: null });
    await act(async () => {});
    expect(api.verifySignIn).not.toHaveBeenCalled();
  });
});
