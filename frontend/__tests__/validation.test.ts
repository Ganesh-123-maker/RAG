import { describe, it, expect } from "vitest";
import { validateUploadFile } from "@/lib/validation";

describe("upload validation (mirrors backend 50 MB / pdf,docx,txt,md)", () => {
  it("accepts each allowed type under the limit", () => {
    for (const name of ["a.pdf", "a.docx", "a.txt", "a.md", "A.PDF"]) {
      expect(validateUploadFile({ name, size: 1024 })).toBeNull();
    }
  });

  it("rejects disallowed types, oversize files, and empty files with a clear message", () => {
    expect(validateUploadFile({ name: "a.exe", size: 10 })).toMatch(/Unsupported file type/);
    expect(validateUploadFile({ name: "a", size: 10 })).toMatch(/Unsupported file type/);
    expect(validateUploadFile({ name: "a.pdf", size: 51 * 1024 * 1024 })).toMatch(/over the 50 MB limit/);
    expect(validateUploadFile({ name: "a.pdf", size: 0 })).toMatch(/empty/);
    expect(validateUploadFile({ name: "a.pdf", size: 50 * 1024 * 1024 })).toBeNull();
  });
});
