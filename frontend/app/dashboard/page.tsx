"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Brain,
  Upload,
  MessageSquare,
  FileText,
  LogOut,
  Plus,
  Trash2,
  CheckCircle,
  Clock,
  AlertCircle,
  ChevronRight,
  Loader2,
  Menu,
  X,
  Pencil,
  RotateCcw,
} from "lucide-react";
import toast from "react-hot-toast";
import { useDropzone } from "react-dropzone";
import { authApi, getApiErrorMessage, type Document, type Conversation } from "@/lib/api";
import { validateUploadFile } from "@/lib/validation";
import ChatPanel from "@/components/ChatPanel";

type View = "upload" | "chat";

const TERMINAL_DOC_STATUSES = ["ready", "error"];
const isNonTerminal = (d: Document) => !TERMINAL_DOC_STATUSES.includes(d.status);

export default function DashboardPage() {
  const router = useRouter();
  const [view, setView] = useState<View>("upload");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [convsError, setConvsError] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [visibleConvCount, setVisibleConvCount] = useState(15);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDocs = useCallback(async () => {
    try {
      const docsRes = await authApi().get("/api/v1/documents/");
      setDocuments(docsRes.data.documents || []);
      setDocsError(null);
    } catch (err) {
      setDocsError(getApiErrorMessage(err));
    }
  }, []);

  const fetchConvs = useCallback(async () => {
    try {
      const convsRes = await authApi().get("/api/v1/chat/conversations");
      setConversations(convsRes.data.conversations || []);
      setConvsError(null);
    } catch (err) {
      setConvsError(getApiErrorMessage(err));
    }
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const meRes = await authApi().get("/api/v1/auth/me");
      setUserEmail(meRes.data.email);
      await Promise.all([fetchDocs(), fetchConvs()]);
    } catch (authErr) {
      // /me failure means the session is gone (401 interceptor
      // also redirects); stay out of a half-loaded dashboard.
      if ((authErr as { response?: { status?: number } })?.response?.status !== 401) {
        toast.error(getApiErrorMessage(authErr));
      }
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router, fetchDocs, fetchConvs]);

  // Phase E: no cookie presence check is possible (httpOnly).
  // fetchData proves auth via GET /me and redirects on failure.
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll document status only while any document is non-terminal
  // (queued/processing), every 2.5s; stop as soon as all are
  // terminal so a ready library costs no polling traffic.
  useEffect(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (documents.some(isNonTerminal)) {
      pollingRef.current = setInterval(() => {
        void fetchDocs();
      }, 2500);
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [documents, fetchDocs]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    const validationError = validateUploadFile(file);
    if (validationError) {
      toast.error(validationError);
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      await authApi().post("/api/v1/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`"${file.name}" uploaded and indexed!`);
      await fetchDocs();
    } catch (err: unknown) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }, [fetchDocs]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected: (rejections) => {
      const first = rejections[0];
      const message = first?.errors?.[0]?.message;
      toast.error(message || "File rejected. Allowed: PDF, DOCX, TXT, MD, max 50 MB.");
    },
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
      "text/markdown": [".md"],
    },
    maxFiles: 1,
    maxSize: 50 * 1024 * 1024,
    disabled: uploading,
  });

  const deleteDocument = async (docId: string, name: string) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      await authApi().delete(`/api/v1/documents/${docId}`);
      toast.success("Document deleted");
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const deleteConversation = async (e: React.MouseEvent, convId: string) => {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    try {
      await authApi().delete(`/api/v1/chat/conversations/${convId}`);
      toast.success("Conversation deleted");
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const saveRename = async (convId: string) => {
    const title = renameValue.trim();
    if (!title) {
      toast.error("Title cannot be empty");
      return;
    }
    try {
      await authApi().patch(`/api/v1/chat/conversations/${convId}`, { title });
      setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, title } : c)));
      setRenamingId(null);
      toast.success("Conversation renamed");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  };

  const handleLogout = async () => {
    // Phase E: revoke server-side (denylist) and clear the httpOnly
    // cookie; a JS-only cookie removal would not revoke the token.
    try {
      await authApi().post("/api/v1/auth/logout");
    } catch {
      // Still navigate to login even if logout fails.
    }
    router.push("/login");
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case "ready":
        return <span className="badge-ready"><CheckCircle className="w-3 h-3" /> Ready</span>;
      case "queued":
        return <span className="badge-processing"><Clock className="w-3 h-3" /> Queued</span>;
      case "processing":
        return <span className="badge-processing"><Clock className="w-3 h-3" /> Processing</span>;
      case "error":
        return <span className="badge-error"><AlertCircle className="w-3 h-3" /> Error</span>;
      default:
        return null;
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading dashboard">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-brand-400 animate-spin" />
          <p className="text-slate-400">Loading your knowledge base…</p>
          {/* Skeleton rows: the page is loading, not empty. */}
          <div className="w-72 space-y-2" aria-hidden="true">
            <div className="h-10 rounded-xl bg-surface-card animate-pulse" />
            <div className="h-10 rounded-xl bg-surface-card animate-pulse" />
            <div className="h-10 rounded-xl bg-surface-card animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  const sidebar = (
    <>
      <div className="p-6 border-b border-surface-border">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-slate-100">RAG Assistant</span>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
            className="ml-auto btn-ghost !p-2 md:hidden"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-slate-500 mt-1 truncate">{userEmail}</p>
      </div>

      <nav className="p-4 space-y-1 flex-1 overflow-y-auto" aria-label="Main navigation">
        <button
          type="button"
          onClick={() => { setView("upload"); setSidebarOpen(false); }}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
            view === "upload"
              ? "bg-brand-600/20 text-brand-300 border border-brand-500/30"
              : "text-slate-400 hover:text-slate-200 hover:bg-surface-hover"
          }`}
        >
          <FileText className="w-4 h-4" />
          Documents
          <span className="ml-auto text-xs bg-surface text-slate-400 px-2 py-0.5 rounded-full">
            {documents.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => { setView("chat"); setActiveConvId(null); setSidebarOpen(false); }}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
            view === "chat" && !activeConvId
              ? "bg-brand-600/20 text-brand-300 border border-brand-500/30"
              : "text-slate-400 hover:text-slate-200 hover:bg-surface-hover"
          }`}
        >
          <Plus className="w-4 h-4" />
          New chat
        </button>

        <div className="pt-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2">
            Recent chats
          </p>
          {convsError ? (
            <div className="px-3 py-2 text-sm text-red-300" role="alert">
              <p>Could not load conversations: {convsError}</p>
              <button type="button" onClick={() => void fetchConvs()} className="btn-ghost text-xs mt-2">
                <RotateCcw className="w-3 h-3" /> Retry
              </button>
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-3 py-2 text-sm text-slate-500">No conversations yet — start a new chat.</p>
          ) : (
            <>
              {conversations.slice(0, visibleConvCount).map((conv) => (
                <div
                  key={conv.id}
                  onClick={() => { setActiveConvId(conv.id); setView("chat"); setSidebarOpen(false); }}
                  className={`group w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl text-sm transition-all text-left cursor-pointer ${
                    activeConvId === conv.id
                      ? "bg-brand-600/20 text-brand-300 border border-brand-500/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-surface-hover"
                  }`}
                >
                  {renamingId === conv.id ? (
                    <span className="flex items-center gap-2 w-full" onClick={(e) => e.stopPropagation()}>
                      <input
                        autoFocus
                        aria-label={`Rename conversation ${conv.title}`}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveRename(conv.id);
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        className="input !py-1.5 !px-2 text-sm flex-1 min-w-0"
                      />
                      <button type="button" onClick={() => void saveRename(conv.id)} aria-label="Save new title" className="btn-ghost !p-1.5 text-xs">Save</button>
                      <button type="button" onClick={() => setRenamingId(null)} aria-label="Cancel rename" className="btn-ghost !p-1.5 text-xs">Cancel</button>
                    </span>
                  ) : (
                    <>
                      <div className="flex items-center gap-2.5 truncate">
                        <MessageSquare className="w-4 h-4 flex-shrink-0" />
                        <span className="truncate">{conv.title}</span>
                      </div>
                      <span className="flex gap-1 flex-shrink-0">
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setRenamingId(conv.id); setRenameValue(conv.title); }}
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 hover:text-brand-300 transition-opacity text-slate-500"
                          aria-label={`Rename conversation ${conv.title}`}
                          title="Rename conversation"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => deleteConversation(e, conv.id)}
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 hover:text-red-400 transition-opacity text-slate-500"
                          aria-label={`Delete conversation ${conv.title}`}
                          title="Delete conversation"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </span>
                    </>
                  )}
                </div>
              ))}
              {visibleConvCount < conversations.length && (
                <button type="button" onClick={() => setVisibleConvCount((n) => n + 15)} className="btn-ghost text-xs w-full justify-center mt-2">
                  Load more chats ({conversations.length - visibleConvCount} remaining)
                </button>
              )}
            </>
          )}
        </div>
      </nav>

      <div className="p-4 border-t border-surface-border">
        <button type="button" onClick={handleLogout} className="btn-ghost w-full justify-start text-sm">
          <LogOut className="w-4 h-4" />
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen flex">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-72 flex-shrink-0 border-r border-surface-border bg-surface-card flex-col">
        {sidebar}
      </aside>

      {/* Mobile sidebar: overlay, not a fixed w-72 bar. */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
          <div className="absolute inset-0 bg-black/60" onClick={() => setSidebarOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-surface-border bg-surface-card flex flex-col overflow-y-auto">
            {sidebar}
          </aside>
        </div>
      )}

      <main className="flex-1 flex flex-col min-h-0 overflow-hidden min-w-0">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-surface-border bg-surface-card">
          <button type="button" onClick={() => setSidebarOpen(true)} aria-label="Open navigation menu" className="btn-ghost !p-2">
            <Menu className="w-5 h-5" />
          </button>
          <span className="font-semibold text-slate-100 text-sm">RAG Assistant</span>
        </div>

        {view === "upload" ? (
          <div className="flex-1 overflow-y-auto p-4 sm:p-8">
            <div className="max-w-4xl mx-auto">
              <div className="mb-8">
                <h1 className="text-2xl font-bold text-slate-100">Document Library</h1>
                <p className="text-slate-400 mt-1">
                  Upload documents to build your knowledge base. Supports PDF, DOCX, TXT, and MD.
                </p>
              </div>

              <div
                {...getRootProps()}
                className={`relative border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all duration-200 mb-8 ${
                  isDragActive
                    ? "border-brand-500 bg-brand-600/10"
                    : uploading
                    ? "border-surface-border bg-surface-hover cursor-not-allowed"
                    : "border-surface-border hover:border-brand-500/50 hover:bg-surface-hover"
                }`}
              >
                <input {...getInputProps()} id="file-upload" aria-label="Upload a document" />
                <div className="flex flex-col items-center gap-4">
                  {uploading ? (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-brand-600/10 flex items-center justify-center">
                        <Loader2 className="w-7 h-7 text-brand-400 animate-spin" />
                      </div>
                      <div>
                        <p className="font-semibold text-slate-200">Processing document…</p>
                        <p className="text-slate-400 text-sm mt-1">Chunking, embedding, indexing in Qdrant</p>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all ${
                        isDragActive ? "bg-brand-600/20" : "bg-surface"
                      }`}>
                        <Upload className={`w-7 h-7 ${isDragActive ? "text-brand-400" : "text-slate-500"}`} />
                      </div>
                      <div>
                        <p className="font-semibold text-slate-200">
                          {isDragActive ? "Drop it here!" : "Drop a file or click to upload"}
                        </p>
                        <p className="text-slate-500 text-sm mt-1">PDF · DOCX · TXT · MD · Max 50 MB</p>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {docsError ? (
                <div className="card p-6 text-center" role="alert">
                  <p className="text-red-300">Could not load documents: {docsError}</p>
                  <button type="button" onClick={() => void fetchDocs()} className="btn-ghost text-sm mt-3">
                    <RotateCcw className="w-3.5 h-3.5" /> Retry
                  </button>
                </div>
              ) : documents.length === 0 ? (
                <div className="card p-12 text-center">
                  <FileText className="w-12 h-12 text-slate-600 mx-auto mb-4" />
                  <p className="text-slate-400 text-lg font-medium">No documents yet</p>
                  <p className="text-slate-500 text-sm mt-1">Upload your first document above to get started</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {documents.map((doc) => (
                    <div key={doc.id} className="card-hover p-5 flex items-center gap-4 group">
                      <div className="w-10 h-10 rounded-xl bg-brand-600/10 flex items-center justify-center flex-shrink-0">
                        <FileText className="w-5 h-5 text-brand-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-slate-200 truncate">{doc.original_name}</p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {formatBytes(doc.file_size_bytes)} · {doc.chunk_count} chunks ·{" "}
                          {new Date(doc.created_at).toLocaleDateString()}
                        </p>
                        {isNonTerminal(doc) && (
                          <div className="mt-2 h-1.5 rounded-full bg-surface overflow-hidden" role="progressbar" aria-valuenow={doc.ingestion_progress ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={`Ingestion progress for ${doc.original_name}`}>
                            <div className="h-full bg-brand-500 transition-all" style={{ width: `${doc.ingestion_progress ?? 0}%` }} />
                          </div>
                        )}
                        {doc.status === "error" && doc.error_message && (
                          <p className="text-xs text-red-300 mt-1" role="alert">{doc.error_message}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        {statusBadge(doc.status)}
                        {doc.status === "ready" && (
                          <button
                            type="button"
                            onClick={() => { setView("chat"); setActiveConvId(null); }}
                            className="opacity-0 group-hover:opacity-100 focus:opacity-100 btn-ghost text-xs py-1.5 transition-opacity"
                          >
                            Ask <ChevronRight className="w-3 h-3" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => deleteDocument(doc.id, doc.original_name)}
                          aria-label={`Delete document ${doc.original_name}`}
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 btn-danger text-xs py-1.5 transition-opacity"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <ChatPanel
            conversationId={activeConvId}
            onConversationCreated={(id) => {
              setActiveConvId(id);
              fetchConvs();
            }}
          />
        )}
      </main>
    </div>
  );
}
