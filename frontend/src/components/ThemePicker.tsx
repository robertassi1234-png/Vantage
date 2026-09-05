import { useEffect, useRef, useState } from "react";
import { THEMES, type Theme } from "../useTheme";

const OPTIONS: Record<Theme, { name: string; description: string; colors: string[] }> = {
  system: { name: "Automatic", description: "Follows your device", colors: ["#f4f5f9", "#15171f", "#7c76f1"] },
  light: { name: "Daylight", description: "Clean and bright", colors: ["#f4f5f9", "#ffffff", "#4f46e5"] },
  dark: { name: "Graphite", description: "Quiet contrast", colors: ["#0a0b10", "#20232e", "#aaa5ff"] },
  midnight: { name: "Midnight", description: "Violet after hours", colors: ["#100d20", "#211934", "#c4a5ff"] },
  ocean: { name: "Ocean", description: "Deep blue, clear focus", colors: ["#071922", "#102d3b", "#67dbec"] },
  forest: { name: "Forest", description: "A calmer perspective", colors: ["#101c17", "#20382b", "#bbda92"] },
  paper: { name: "Paper", description: "Warm and considered", colors: ["#f4efe5", "#fffcf5", "#795339"] },
};

export function ThemePicker({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  return (
    <div className="theme-picker" ref={container} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <button ref={trigger} className="appearance-button" aria-expanded={open}
        aria-controls="appearance-panel" onClick={() => setOpen(!open)}>
        <span aria-hidden="true">◐</span> <span>Themes</span>
      </button>
      {open && <section id="appearance-panel" className="appearance-panel" aria-label="Appearance">
        <div className="appearance-heading"><strong>Make it your space</strong><span>Choose your perspective.</span></div>
        <div className="theme-options">
          {THEMES.map((option) => <button key={option} className="theme-option" aria-pressed={theme === option}
            onClick={() => onChange(option)}>
            <span className="theme-preview" aria-hidden="true" style={{ background: OPTIONS[option].colors[0] }}>
              <span style={{ background: OPTIONS[option].colors[1] }} />
              <i style={{ background: OPTIONS[option].colors[2] }} />
            </span>
            <span className="theme-name">{OPTIONS[option].name}<span aria-hidden="true">{theme === option ? "✓" : ""}</span></span>
            <small>{OPTIONS[option].description}</small>
          </button>)}
        </div>
        <p className="appearance-note">Your choice is saved on this device.</p>
      </section>}
    </div>
  );
}
