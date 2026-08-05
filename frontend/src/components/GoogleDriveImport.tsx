import { useEffect, useState } from "react";

import {
  getGoogleDriveStatus,
  importGoogleDriveFiles,
  listGoogleDriveFiles,
  loginGoogleDrive,
  type DriveFile,
} from "../lib/api";

interface GoogleDriveImportProps {
  activeWorkspaceId: string | null;
  onImported: () => void;
}

export function GoogleDriveImport({ activeWorkspaceId, onImported }: GoogleDriveImportProps) {
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    void (async () => {
      setError(null);
      try {
        const status = await getGoogleDriveStatus();
        setConnected(status.connected);
        if (status.connected) {
          const listing = await listGoogleDriveFiles();
          setFiles(listing.files);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [open]);

  async function handleConnect() {
    try {
      const { redirect_url } = await loginGoogleDrive();
      window.location.assign(redirect_url);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function toggleSelected(fileId: string) {
    setSelected((current) =>
      current.includes(fileId) ? current.filter((id) => id !== fileId) : [...current, fileId],
    );
  }

  async function handleImport() {
    if (!activeWorkspaceId || selected.length === 0) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await importGoogleDriveFiles(activeWorkspaceId, selected);
      setSelected([]);
      onImported();
      setOpen(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="drive-import">
      <button className="button ghost" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide Google Drive" : "Import from Google Drive"}
      </button>
      {open && (
        <div className="drive-import-panel">
          {error && (
            <p className="error-banner" role="alert">
              {error}
            </p>
          )}
          {connected === false && (
            <>
              <p className="muted">
                Connect Google Drive to import supported files (pdf, docx, pptx, csv, Google Docs/Slides).
                Imported files behave exactly like local files — only the one-time fetch uses your Google
                account.
              </p>
              <button className="button" onClick={() => void handleConnect()}>
                Connect Google Drive
              </button>
            </>
          )}
          {connected === true && (
            <>
              {files.length === 0 && <p className="muted">No importable files found in this Drive.</p>}
              <div className="drive-file-list">
                {files.map((file) => (
                  <label key={file.id} className={`drive-file-row ${file.importable ? "" : "disabled"}`}>
                    <input
                      type="checkbox"
                      checked={selected.includes(file.id)}
                      disabled={!file.importable}
                      onChange={() => toggleSelected(file.id)}
                    />
                    <span>{file.name}</span>
                    {!file.importable && <span className="pill">unsupported</span>}
                  </label>
                ))}
              </div>
              <button
                className="button"
                onClick={() => void handleImport()}
                disabled={!activeWorkspaceId || selected.length === 0 || loading}
              >
                {loading ? "Importing..." : `Import Selected (${selected.length})`}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
