import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  confirmStudentContact,
  setStudentContact,
  studentContacts,
  type NotificationChannel,
} from "../api/notifications";
import ContactEditor from "../components/ContactEditor";
import { Button } from "../components/controls";
import { SectionSkeleton } from "../components/page";
import { SectionCard, SectionHeader } from "../components/ui";

const CHANNELS: NotificationChannel[] = ["whatsapp", "email"];

/**
 * Where this learner and their parents are reached. The tutor enters each
 * address and confirms it after seeing it shown back; nothing is sent to an
 * unconfirmed one (threat review F5). A parent appears here once they have
 * joined with the parent link.
 */
export default function StudentContacts({ studentId }: { studentId: number }) {
  const queryClient = useQueryClient();
  const key = ["student-contacts", studentId];
  const people = useQuery({ queryKey: key, queryFn: () => studentContacts(studentId) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });

  return (
    <SectionCard>
      <SectionHeader
        title="Messages"
        description="Weekly summaries, homework and reminders go to these numbers."
      />
      {people.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={3} label="Loading contact details" />
        </div>
      ) : people.isError ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            The contact details didn&apos;t load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => people.refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          {(people.data ?? []).map((person) => {
            const isParent = person.role === "parent";
            return (
              <div key={person.user_id}>
                <h4 className="text-sm font-medium text-ink-900">
                  {person.name}
                  <span className="ml-2 font-normal text-ink-500">
                    {isParent ? "Parent" : "Student"}
                  </span>
                </h4>
                <div className="mt-2 grid gap-5 sm:grid-cols-2">
                  {CHANNELS.map((channel) => (
                    <ContactEditor
                      key={channel}
                      who={person.name}
                      channel={channel}
                      contact={person.contacts.find((c) => c.channel === channel)}
                      onSave={(address) =>
                        setStudentContact(studentId, {
                          channel,
                          address,
                          ...(isParent ? { user_id: person.user_id } : {}),
                        }).then(refresh)
                      }
                      onConfirm={(id) => confirmStudentContact(studentId, id).then(refresh)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          {(people.data ?? []).every((p) => p.role !== "parent") && (
            <p className="text-sm text-ink-500">
              No parent has joined yet. Once one does, with the parent link above, you can add their
              number here.
            </p>
          )}
        </div>
      )}
    </SectionCard>
  );
}
