import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * A last line of defence against a blank page.
 *
 * React unmounts the whole tree when a render throws, so without this one bad
 * value anywhere -- a malformed response, an unexpected null -- leaves the
 * reader looking at nothing at all, with no hint that anything is wrong or
 * what to do about it. A message and a reload button is a far better worst
 * case, and it keeps the failure reportable instead of invisible.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept in the console so a crash can still be diagnosed after the fact.
    console.error("Vantage crashed while rendering:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="crash">
        <h2>Something went wrong on this page</h2>
        <p>
          Vantage hit an unexpected problem while drawing this view. Your watchlist and
          alerts are stored on the server, so nothing has been lost.
        </p>
        <div className="crash-actions">
          <button className="btn" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
        <details>
          <summary>Technical details</summary>
          <pre>{this.state.error.message}</pre>
        </details>
      </div>
    );
  }
}
