import { useState } from "react";

interface Props {
  ticker: string;
  /** The price on screen right now. Stamped with the entry and never recomputed. */
  priceNow: number | null;
  suggestedTags: string[];
  onSubmit: (entry: { body: string; tags: string[]; priceAtWrite: number | null }) => Promise<void>;
  onCancel?: () => void;
  autoFocus?: boolean;
}

/**
 * Writing an entry.
 *
 * The price the reader is looking at goes in with it, which is why the form
 * says so plainly: what gets recorded is the number on their screen, not
 * whatever a later fetch returns.
 */
export function JournalComposer({
  ticker,
  priceNow,
  suggestedTags,
  onSubmit,
  onCancel,
  autoFocus,
}: Props) {
  const [body, setBody] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(tag: string) {
    setTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) {
      setError("Write something first.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ body: body.trim(), tags, priceAtWrite: priceNow });
      setBody("");
      setTags([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="journal-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor={`journal-${ticker}`}>
        What you think about {ticker}
      </label>
      <textarea
        id={`journal-${ticker}`}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={3}
        maxLength={4000}
        autoFocus={autoFocus}
        placeholder={`What do you think about ${ticker}, and why? You'll read this back in a year.`}
      />

      <div className="journal-tag-picker" role="group" aria-label="Tags">
        {suggestedTags.map((tag) => (
          <button
            key={tag}
            type="button"
            className={`tag-chip${tags.includes(tag) ? " active" : ""}`}
            onClick={() => toggle(tag)}
            aria-pressed={tags.includes(tag)}
          >
            {tag}
          </button>
        ))}
      </div>

      <div className="journal-composer-actions">
        <button className="btn btn-small" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save entry"}
        </button>
        {onCancel && (
          <button className="ghost-btn" type="button" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        )}
        <span className="journal-stamp-note">
          {priceNow == null
            ? `No price for ${ticker} right now — this will be saved without one.`
            : `Saved against ${ticker} at $${priceNow.toFixed(2)}, so you can grade it later.`}
        </span>
      </div>

      {error && <p className="lot-error">{error}</p>}
    </form>
  );
}
