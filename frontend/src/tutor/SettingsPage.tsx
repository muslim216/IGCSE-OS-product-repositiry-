import TimezoneSetting from "./TimezoneSetting";
import MyTimezoneSetting from "../components/MyTimezoneSetting";

/**
 * The tutor's settings.
 *
 * This page used to be `ClassroomSettingsPage` and was mostly a Google
 * Classroom connect/sync/link surface, with the timezone control above it.
 * Classroom is hidden from the product (AV-58) — its backend code, service,
 * models and tables are all kept and only its router is unmounted — so what
 * remains here is the timezone.
 *
 * Kept as a page rather than folded into another surface because the route
 * `/tutor/settings` is linked from the Library and because Phase D settles
 * where settings live; collapsing it now would be a navigation decision this
 * task does not own.
 */
export default function SettingsPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <TimezoneSetting />
      <MyTimezoneSetting />
    </div>
  );
}
