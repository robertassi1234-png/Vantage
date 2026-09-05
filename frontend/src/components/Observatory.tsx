import { useState } from "react";

/** Decorative CSS geometry, deliberately independent of market data. */
export function Observatory() {
  const [paused, setPaused] = useState(false);
  return <section className={`observatory ${paused ? "motion-paused" : ""}`} aria-label="Your research workspace">
    <div className="observatory-copy">
      <span className="eyebrow"><i /> THE VANTAGE OBSERVATORY</span>
      <h2>See the bigger picture.<br /><em>Find your perspective.</em></h2>
      <p>A quieter space to follow the markets, connect your research, and make your next move a considered one.</p>
      <a className="observatory-link" href="#research-dashboard">Explore your dashboard <span aria-hidden="true">↗</span></a>
      <div className="observatory-tags"><span>01 / FOLLOW</span><span>02 / COMPARE</span><span>03 / REFLECT</span></div>
    </div>
    <div className="orbital-art" aria-hidden="true">
      <div className="orbital-grid" />
      <div className="orbital-halo" />
      <div className="orbital-system">
        <div className="orbital-core" />
        <div className="orbital-ring ring-one" />
        <div className="orbital-ring ring-two" />
        <div className="orbital-ring ring-three" />
        <div className="orbital-moon" />
      </div>
      <div className="orbital-coordinate coordinate-one">V / 01<br /><span>A DIFFERENT ANGLE</span></div>
      <div className="orbital-coordinate coordinate-two">RESEARCH IN ORBIT<br /><span>FORM × PERSPECTIVE</span></div>
    </div>
    <button className="motion-control" onClick={() => setPaused(!paused)} aria-pressed={paused} aria-label={paused ? "Resume decorative animation" : "Pause decorative animation"}>{paused ? "Play motion" : "Pause motion"}</button>
  </section>;
}
