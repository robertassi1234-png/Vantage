import { BackupPanel } from "../components/BackupPanel";
import { ProviderStatus } from "../components/ProviderStatus";

export function SettingsPage() {
  return <section>
    <div className="page-header"><div><h2>Settings</h2><p className="page-subtitle">Your workspace, data connections, and backups.</p></div></div>
    <section className="settings-card"><h3>Appearance & account</h3><p>Use Themes to change your colors. Sign in to sync your watchlist across devices.</p></section>
    <section className="settings-card"><h3>Data connections</h3><p>Check provider availability and how Vantage saves API calls.</p><ProviderStatus defaultOpen /></section>
    <section className="settings-card"><h3>Backup & restore</h3><p>Download a copy of your lists before moving to another device.</p><BackupPanel /></section>
  </section>;
}
