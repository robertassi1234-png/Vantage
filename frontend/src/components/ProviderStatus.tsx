import { useEffect, useState } from "react";
import { api } from "../api";
import type { ProviderStatus as Status } from "../types";

/**
 * Which data providers are answering, and which are not set up.
 *
 * "No data" has three causes that look identical from the outside: a key that
 * was never set, an allowance that has been spent, and a provider that is
 * simply down. Only the reader can fix the first two, and only if they can
 * tell which one they are looking at. The backend has always known; nothing
 * asked it.
 */
export function ProviderStatus({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [open, setOpen] = useState(defaultOpen);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || status) return;
    api
      .getProviderStatus()
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, status]);

  if (!open) {
    return (
      <button className="link-btn provider-toggle" onClick={() => setOpen(true)}>
        Why is data missing?
      </button>
    );
  }

  return (
    <div className="provider-status">
      <div className="provider-head">
        <h4>Data sources</h4>
        <button className="link-btn" onClick={() => setOpen(false)}>
          Hide
        </button>
      </div>

      {error && <p className="notice-line">{error}</p>}
      {!status && !error && <p className="notice-line">Checking…</p>}

      {status && (
        <>
          <ul className="provider-list">
            {status.providers.map((provider) => {
              const state = !provider.configured
                ? "unset"
                : provider.available
                  ? "ok"
                  : "benched";
              return (
                <li key={provider.name} className={`provider-row provider-${state}`}>
                  <span className="provider-name">{provider.name}</span>
                  {/* A word, not just a colour: these three states are the
                      whole point of the panel. */}
                  <span className="provider-state">
                    {state === "unset"
                      ? "no key set"
                      : state === "ok"
                        ? "answering"
                        : `resting ${formatCooldown(provider.cooldown_seconds)}`}
                  </span>
                  <span className="provider-detail">
                    {state === "unset"
                      ? "Free to add — another allowance to fall back on"
                      : (provider.reason ?? provider.last_error ?? "")}
                  </span>
                </li>
              );
            })}
          </ul>

          <p className="provider-summary">
            {status.healthy === 0
              ? "Nothing is answering right now. Adding a key for any provider above gives the app another allowance to fall through to."
              : `${status.healthy} of ${status.providers.length} answering. Vantage tries them in order and uses the first that works.`}
          </p>
        </>
      )}
    </div>
  );
}

function formatCooldown(seconds: number): string {
  if (seconds <= 0) return "briefly";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.round(minutes / 60)}h`;
}
