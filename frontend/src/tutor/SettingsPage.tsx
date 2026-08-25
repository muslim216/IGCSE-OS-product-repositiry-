import TimezoneSetting from "./TimezoneSetting";
import MyTimezoneSetting from "../components/MyTimezoneSetting";

/**
 * This was `ClassroomSettingsPage` until 0.5 (AV-58) hid the Google Classroom
 * surface. The timezone controls shipped in 0.7 lived on that page and are the
 * only way to set the organization's zone and the reader's own — Phase 6's plan
 * weeks, Phase 7's lesson dates and Phase 8's weekly send all depend on them —
 * so the page stays and loses only the Classroom half.
 *
 * The URL is unchanged, so an existing bookmark still lands.
 */
export default function SettingsPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-xl font-semibold text-ink-900">Settings</h2>
      <TimezoneSetting />
      <MyTimezoneSetting />
    </div>
  );
}
