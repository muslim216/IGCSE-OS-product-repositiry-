import TimezoneSetting from "./TimezoneSetting";
import CustomCriteriaSetting from "./CustomCriteriaSetting";
import IntegrationsSetting from "./IntegrationsSetting";
import MyTimezoneSetting from "../components/MyTimezoneSetting";
import { PageHeader } from "../components/page";

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
    <div className="max-w-2xl">
      <PageHeader
        title="Settings"
        description="The time zones days are counted in, the criteria you score students on by hand, and Zoom and Google Meet for online attendance."
        back={{ to: "/tutor/library", label: "Library" }}
      />
      <div className="space-y-6">
        <TimezoneSetting />
        <MyTimezoneSetting />
        <CustomCriteriaSetting />
        <IntegrationsSetting />
      </div>
    </div>
  );
}
