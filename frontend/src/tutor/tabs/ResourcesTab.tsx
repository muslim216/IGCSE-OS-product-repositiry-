import { GroupResourcesPanel } from "../GroupResourcesPanel";
import { useGroupContext } from "../GroupLayout";

export default function ResourcesTab() {
  const { groupId } = useGroupContext();
  return <GroupResourcesPanel groupId={groupId} />;
}
