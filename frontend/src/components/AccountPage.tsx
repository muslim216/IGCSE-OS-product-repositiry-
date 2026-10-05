import { Link } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { Button } from "./controls";
import { PageHeader } from "./page";
import { InitialsAvatar, SectionCard, SectionHeader } from "./ui";
import MyTimezoneSetting from "./MyTimezoneSetting";
import NotificationPreferences from "./NotificationPreferences";

const ROLE_LABEL = {
  student: "Student",
  parent: "Parent",
  tutor: "Tutor",
  admin: "Admin",
} as const;

/**
 * The student's and parent's own account page. Personal settings used to sit
 * on their home screens, where a time-zone picker under "You're clear. Nothing
 * due." read as clutter; they live here, one tap from the avatar, the way every
 * other product files them. The tutor's equivalent is /tutor/settings, which
 * also carries organization settings.
 */
export default function AccountPage() {
  const { user, signOut } = useAuth();
  if (!user) return null;
  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader title="Account" description="Your details and preferences." />

      <SectionCard>
        <div className="flex items-center gap-4">
          <InitialsAvatar name={user.name} />
          <div className="min-w-0">
            <p className="truncate font-medium text-ink-900">{user.name}</p>
            <p className="truncate text-sm text-ink-500">
              {ROLE_LABEL[user.role]}
              {user.email ? ` · ${user.email}` : user.username ? ` · ${user.username}` : ""}
            </p>
          </div>
        </div>
        <p className="mt-4 text-sm text-ink-500">
          If any of these details are wrong, tell your tutor — they manage your class.
        </p>
      </SectionCard>

      <MyTimezoneSetting />

      <NotificationPreferences />

      <SectionCard>
        <SectionHeader title="Your data" />
        <p className="mt-2 text-sm text-ink-700">
          Read how avora uses and protects your information in our{" "}
          <Link to="/privacy" className="text-brand-600 underline-offset-2 hover:underline">
            privacy policy
          </Link>
          .
        </p>
      </SectionCard>

      <Button variant="secondary" onClick={signOut}>
        <LogOut aria-hidden className="h-4 w-4" />
        Sign out
      </Button>
    </div>
  );
}
