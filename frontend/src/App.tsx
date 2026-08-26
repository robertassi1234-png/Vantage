import { useState } from "react";
import { ComparisonPage } from "./pages/ComparisonPage";
import { FedTrackerPage } from "./pages/FedTrackerPage";

type Tab = "comparison" | "fed";

function App() {
  const [tab, setTab] = useState<Tab>("comparison");

  return (
    <div className="app">
      <header className="app-header">
        <h1>Vantage</h1>
        <nav>
          <button className={tab === "comparison" ? "active" : ""} onClick={() => setTab("comparison")}>
            Stock Comparison
          </button>
          <button className={tab === "fed" ? "active" : ""} onClick={() => setTab("fed")}>
            Fed Tracker
          </button>
        </nav>
      </header>
      <main>{tab === "comparison" ? <ComparisonPage /> : <FedTrackerPage />}</main>
    </div>
  );
}

export default App;
