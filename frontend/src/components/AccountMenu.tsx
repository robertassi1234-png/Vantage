import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Account } from "../types";

interface Props {
  account: Account;
  onSignedIn: () => void | Promise<void>;
  onSignOut: () => void | Promise<void>;
  /** A token pasted in by the /signin?token=... link, verified on mount. */
  pendingToken?: string | null;
  onTokenHandled?: () => void;
}

/**
 * Sign in with a link emailed to you.
 *
 * No password field, because there is no password: the account exists to make
 * one watchlist follow you between devices and to give price alerts somewhere
 * to arrive, and proving you can read your own email is enough for that.
 */
export function AccountMenu({
  account,
  onSignedIn,
  onSignOut,
  pendingToken,
  onTokenHandled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  // A sign-in link lands on the app itself, so the token has to be redeemed
  // here rather than on a page of its own.
  useEffect(() => {
    if (!pendingToken) return;

    let cancelled = false;
    setBusy(true);
    api
      .verifySignIn(pendingToken)
      .then(async (result) => {
        if (cancelled) return;
        const moved = result.claimed.watchlist + result.claimed.alerts;
        setStatus(
          moved > 0
            ? `Signed in. Your ${moved} saved item${moved === 1 ? "" : "s"} moved into your account.`
            : "Signed in.",
        );
        setOpen(true);
        await onSignedIn();
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setOpen(true);
      })
      .finally(() => {
        if (cancelled) return;
        setBusy(false);
        onTokenHandled?.();
      });

    return () => {
      cancelled = true;
    };
  }, [pendingToken, onSignedIn, onTokenHandled]);

  useEffect(() => {
    if (!open) return;
    function onClickAway(e: MouseEvent) {
      if (!panel.current?.contains(e.target as Node)) setOpen(false);
    }
    function onEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickAway);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setStatus(null);
    setDevLink(null);
    try {
      const result = await api.requestSignInLink(email.trim());
      setStatus(result.message);
      setDevLink(result.dev_link ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSignOut() {
    setBusy(true);
    try {
      await onSignOut();
      setStatus(null);
      setEmail("");
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }

  const label = account.signed_in ? (account.email ?? "Account") : "Sign in";

  return (
    <div className="account" ref={panel}>
      <button
        className={`account-trigger${account.signed_in ? " signed-in" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <span aria-hidden="true">{account.signed_in ? "●" : "○"}</span>
        <span className="account-label">{label}</span>
      </button>

      {open && (
        <div className="account-panel" role="dialog" aria-label="Account">
          {account.signed_in ? (
            <>
              <p className="account-email">{account.email}</p>
              <p className="muted">
                Your watchlist and price targets follow this account on any device.
              </p>
              {account.email_delivery ? (
                <p className="muted">Price alerts are emailed to you when they trigger.</p>
              ) : (
                <p className="account-warning">
                  Alerts will show up here, but this server can't send email yet.
                </p>
              )}
              {status && <p className="account-status">{status}</p>}
              {/* A link that fails to redeem still has something to say, even
                  to someone already signed in -- silence reads as a no-op. */}
              {error && <p className="account-error">{error}</p>}
              <button className="ghost" onClick={handleSignOut} disabled={busy}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <p className="muted">
                Sign in to keep your watchlist on every device and get price alerts by
                email. No password — we send you a link.
              </p>

              {!account.accounts_available && account.reason && (
                <p className="account-warning">{account.reason}</p>
              )}

              <form onSubmit={handleSubmit}>
                <label className="sr-only" htmlFor="account-email">
                  Email address
                </label>
                <input
                  id="account-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  required
                />
                <button type="submit" disabled={busy || !email.trim()}>
                  {busy ? "Sending…" : "Email me a link"}
                </button>
              </form>

              {status && <p className="account-status">{status}</p>}
              {devLink && (
                <p className="account-status">
                  <a href={devLink}>Open your sign-in link</a>
                </p>
              )}
              {error && <p className="account-error">{error}</p>}
              <p className="muted">
                Signing in keeps whatever this browser has already saved.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
