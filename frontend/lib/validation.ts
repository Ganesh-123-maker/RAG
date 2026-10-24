import { ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_SIZE_BYTES } from "@/lib/api";

/** Client-side upload validation, mirroring the backend limits
 * (backend/app/core/config.py MAX_UPLOAD_SIZE_MB=50, document
 * service ALLOWED_TYPES pdf/docx/txt/md). The backend still
 * enforces both; this only fails fast with a clear message
 * before any bytes are uploaded. */
export function validateUploadFile(file: { name: string; size: number }): string | null {
  const lower = file.name.toLowerCase();
  const dot = lower.lastIndexOf(".");
  const ext = dot >= 0 ? lower.slice(dot) : "";
  if (!(ALLOWED_UPLOAD_EXTENSIONS as readonly string[]).includes(ext)) {
    return `Unsupported file type "${ext || "(none)"}". Allowed: PDF, DOCX, TXT, MD.`;
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return `File is ${(file.size / (1024 * 1024)).toFixed(1)} MB, over the 50 MB limit.`;
  }
  if (file.size === 0) {
    return "File is empty.";
  }
  return null;
}
