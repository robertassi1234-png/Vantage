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
        setNotice(`Added ${result.added.length} new statement(s).`);
      } else {
        setNotice("No new statements since last check.");
      }
      if (result.errors.length > 0) {
        setError(result.errors.join("; "));
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
      {error && <p className="error-line">{error}</p>}

      {loading ? (
        <p className="notice-line">Loading…</p>
      ) : timeline.length === 0 ? (
        <p className="empty-state">
          No statements cached yet. Click "Check for new statements" to fetch and summarize the
          latest FOMC releases.
        </p>
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
