// Attachment upload helpers shared by the Composer chips and useChat.

// Keep in sync with backend settings.upload_max_bytes (client check is a
// courtesy; the proxy + backend enforce the real limit).
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

// Server-authoritative record of a stored file (UploadResponse).
export type StoredAttachment = {
  name: string; // sanitized server-side name
  path: string; // workspace-relative, e.g. "uploads/report.pdf"
  size: number;
};

// Client-local chip state while an upload is in flight.
export type PendingAttachment = {
  id: string;
  name: string; // original name the user picked
  size: number;
  status: 'uploading' | 'done' | 'error';
  saved?: StoredAttachment; // present once status === 'done'
  error?: string;
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export async function uploadFile(threadId: string, file: File): Promise<StoredAttachment> {
  const form = new FormData();
  form.append('file', file);
  form.append('thread_id', threadId);
  // No Content-Type header: the browser sets multipart/form-data with boundary.
  const res = await fetch('/api/files', { method: 'POST', body: form });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return (await res.json()) as StoredAttachment;
}
