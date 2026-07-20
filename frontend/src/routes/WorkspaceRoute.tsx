import { WorkspaceOverview } from "../components/WorkspaceOverview";
import type { IndexHistoryEntry, StoredWorkspaceRecord } from "../lib/storage";
import type { IndexEvent } from "../types";

interface WorkspaceRouteProps {
  activeWorkspace: StoredWorkspaceRecord | undefined;
  starterSummary: string;
  indexedDocumentCount: number;
  indexedPages: number;
  lastIndexEntry: IndexHistoryEntry | undefined;
  fileTypeSummary: string;
  indexEvents: IndexEvent[];
  runtimeMode: "live" | "fake" | null;
  busy: boolean;
  noBackend: boolean;
  formatDateTime: (value?: string) => string;
  formatRelative: (value?: string) => string;
}

export function WorkspaceRoute(props: WorkspaceRouteProps) {
  return <WorkspaceOverview {...props} />;
}
