import { useRef, useState } from "react";
import { useCurrentAccount } from "../AccountContext";
import { api } from "../api";
import type { ImportResult, WorkspaceExport } from "../types";

/**
 * Export and import the whole workspace.
 *
 * Signed out, the space id lives in this browser's localStorage, so clearing
 * site data or moving to another device loses the lists, and a file is the
 * honest fix. Signed in, the account already handles that -- but a file still
 * works offline, and is the only way to hand a list to someone else.
 */
export function BackupPanel() {
  const account = useCurrentAccount();
  const fileInput = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.exportWorkspace();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `vantage-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);

      const counts = Object.values(data.lists).reduce((n, l) => n + l.length, 0);
      setStatus(`Saved ${counts} ticker${counts === 1 ? "" : "s"} and ${data.alerts.length} alert${data.alerts.length === 1 ? "" : "s"}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setBusy(true);
    setStatus(null);
    setError(null);
    try {
      const parsed = JSON.parse(await file.text()) as WorkspaceExport;
      if (typeof parsed?.version !== "number" || !parsed.lists) {
        throw new Error("That doesn't look like a Vantage backup file.");
      }

      const result: ImportResult = await api.importWorkspace(parsed);
      const added = Object.entries(result.added)
        .filter(([, n]) => n > 0)
        .map(([list, n]) => `${n} to ${list}`)
        .join(", ");

      // Trades are counted separately because they are the one thing here
      // that is not de-duplicated: two identical purchases are a real thing,
      // so importing the same file twice doubles a position. Saying how many
      // came in is what makes that visible.
      const parts = [
        added,
        result.alerts_added ? `${result.alerts_added} alert(s)` : "",
        result.lots_added ? `${result.lots_added} trade(s)` : "",
      ].filter(Boolean);

      setStatus(
        parts.length
          ? `Restored ${parts.join(", ")}. Reload to see them.`
          : "Everything in that file was already here.",
      );
      if (result.skipped.length) setError(`Skipped: ${result.skipped.join("; ")}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      // Allow re-selecting the same file after a failed attempt.
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <div className="backup-panel">
      <p className="backup-note">
        {account.signed_in
          ? "Your lists are saved to your account and already follow you between devices. A backup file is still useful to keep a copy offline or share one with someone else."
          : "Your lists live in this browser only. Save a backup file to move them to another device, or to get them back if you clear your browser data."}
      </p>

      <div className="backup-actions">
        <button className="btn btn-secondary" onClick={handleExport} disabled={busy}>
          Download backup
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => fileInput.current?.click()}
          disabled={busy}
        >
          Restore from file
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          onChange={handleFile}
          className="visually-hidden"
          aria-label="Choose a Vantage backup file"
        />
      </div>

      {status && <p className="notice-line">{status}</p>}
      {error && <p className="error-line">{error}</p>}
    </div>
  );
}
