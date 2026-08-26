import { useEffect, useState } from "react";
import { api } from "../api";
import type { FedStatement, Sentiment } from "../types";

const SENTIMENT_CLASS: Record<Sentiment, string> = {
  hawkish: "sentiment-hawkish",
  dovish: "sentiment-dovish",
  neutral: "sentiment-neutral",
};

export function FedTrackerPage() {
  const [timeline, setTimeline] = useState<FedStatement[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadTimeline() {
    setLoading(true);
    setError(null);
    try {
      setTimeline(await api.getFedTimeline());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTimeline();
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.refreshFedTimeline();
      setTimeline(result.timeline);
      if (result.added.length > 0) {
        const n = result.added.length;
        setNotice(`Added ${n} new statement${n === 1 ? "" : "s"}.`);
      } else if (result.errors.length === 0) {
        setNotice("You're up to date — no new statements since last check.");
      }
      if (result.errors.length > 0) {
        setError(result.errors.join(" "));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Fed Policy Tracker</h2>
          <p className="page-subtitle">Tone and takeaways from recent FOMC statements.</p>
        </div>
        <button className="btn" onClick={handleRefresh} disabled={refreshing}>
          {refreshing && <span className="spinner" />}
          {refreshing ? "Checking federalreserve.gov…" : "Check for new statements"}
        </button>
      </div>

      {notice && <p className="notice-line">{notice}</p>}
      {error && (
        <div className="alert alert-error">
          <p>{error}</p>
        </div>
      )}

      {loading ? (
        <p className="notice-line">Loading…</p>
      ) : timeline.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No statements yet</p>
          <p>
            Click “Check for new statements” to pull the latest releases from
            federalreserve.gov and summarize their tone.
          </p>
        </div>
      ) : (
        <ul className="fed-timeline">
          {timeline.map((item) => (
            <li
              key={item.id}
              className={`fed-item${item.sentiment ? ` ${SENTIMENT_CLASS[item.sentiment]}` : ""}`}
            >
              <div className="fed-item-header">
                <span className="fed-date">{item.date}</span>
                {item.sentiment && (
                  <span className={`sentiment-badge ${SENTIMENT_CLASS[item.sentiment]}`}>
                    {item.sentiment}
                  </span>
                )}
              </div>
              <a href={item.url} target="_blank" rel="noreferrer" className="fed-title">
                {item.title}
              </a>
              {item.summary && <p className="fed-summary">{item.summary}</p>}
              {item.key_takeaways.length > 0 && (
                <ul className="fed-takeaways">
                  {item.key_takeaways.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
