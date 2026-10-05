import { Navigate, useLocation } from "react-router-dom";
import TimezoneSetting from "./TimezoneSetting";
import CustomCriteriaSetting from "./CustomCriteriaSetting";
import IntegrationsSetting from "./IntegrationsSetting";
import WeeklySendSetting from "./WeeklySendSetting";
import MessagesSetting from "./MessagesSetting";
import MyTimezoneSetting from "../components/MyTimezoneSetting";
import { PageHeader } from "../components/page";
import { PlainSection, SectionIndex, useFollowHash } from "./SectionedPage";
import { SUBJECT_SETUP_SECTIONS } from "./SubjectSetupPage";

/**
 * The tutor's account settings, as sections of one page. It used to be five
 * separate pages parked on the Library shelf beside the teaching material; the
 * coherence pass folded them into this page, composing each in whole rather
 * than rewriting it (EmbeddedPageContext turns a PageHeader into a section
 * heading).
 *
 * Everything that belongs to a subject (teaching guidance, marking rules, grade
 * boundaries, mistake categories, preferences) then moved to Subject setup
 * (9.3a, owner decision 2026-10-05), leaving what belongs to the tutor: the
 * messages Avora sends and the account half. A link to one of the moved
 * sections (`/tutor/settings#boundaries`, from two days of bookmarks and the
 * old redirects) is forwarded there, so it still lands.
 *
 * This was `ClassroomSettingsPage` until 0.5 (AV-58) hid the Google Classroom
 * surface; the account half (time zones, criteria, integrations) stays last.
 */
export const SETTINGS_SECTIONS = [
  { id: "messages", label: "Messages" },
  { id: "account", label: "Account and integrations" },
] as const;

const MOVED_TO_SUBJECT_SETUP = new Set<string>(SUBJECT_SETUP_SECTIONS.map((s) => s.id));

export default function SettingsPage() {
  const { hash, search } = useLocation();
  useFollowHash();

  const moved = decodeURIComponent(hash.slice(1));
  if (MOVED_TO_SUBJECT_SETUP.has(moved)) {
    return <Navigate to={{ pathname: "/tutor/subject-setup", search, hash }} replace />;
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Settings"
        description="The messages Avora sends you, and the time zones, criteria and integrations behind your account. What belongs to a subject is in Subject setup."
      />
      <SectionIndex label="Settings sections" sections={SETTINGS_SECTIONS} />
      <div className="space-y-10">
        <PlainSection id="messages" label="Messages">
          <div className="space-y-6">
            <WeeklySendSetting />
            <MessagesSetting />
          </div>
        </PlainSection>
        <PlainSection id="account" label="Account and integrations">
          <div className="space-y-6">
            <TimezoneSetting />
            <MyTimezoneSetting />
            <CustomCriteriaSetting />
            <IntegrationsSetting />
          </div>
        </PlainSection>
      </div>
    </div>
  );
}
