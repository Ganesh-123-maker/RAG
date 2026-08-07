"use client";

import { useEffect, useState, useCallback } from "react";
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
} from "lucide-react";
import Cookies from "js-cookie";
import toast from "react-hot-toast";
import { useDropzone } from "react-dropzone";
import { authApi, type Document, type Conversation } from "@/lib/api";
import ChatPanel from "@/components/ChatPanel";

type View = "upload" | "chat";

export default function DashboardPage() {
  const router = useRouter();
  const [view, setView] = useState<View>("upload");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [userEmail, setUserEmail] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const api = authApi();
      const meRes = await api.get("/api/v1/auth/me");
      setUserEmail(meRes.data.email);

      try {
        const docsRes = await api.get("/api/v1/documents/");
        setDocuments(docsRes.data.documents || []);
      } catch (docErr) {
        console.error("Failed to fetch documents:", docErr);
        setDocuments([]);
      }

      try {
        const convsRes = await api.get("/api/v1/chat/conversations");
        setConversations(convsRes.data.conversations || []);
      } catch (convErr) {
        console.error("Failed to fetch conversations:", convErr);
        setConversations([]);
      }
    } catch (authErr) {
      console.error("Authentication check failed:", authErr);
      Cookies.remove("access_token", { path: "/" });
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const token = Cookies.get("access_token");
    if (!token) {
      router.push("/login");
      return;
    }
    fetchData();
  }, [fetchData, router]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const api = authApi();
      await api.post("/api/v1/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`"${file.name}" uploaded and indexed!`);
      await fetchData();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      toast.error(error.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [fetchData]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
      "text/markdown": [".md"],
    },
    maxFiles: 1,
    disabled: uploading,
  });

  const deleteDocument = async (docId: string, name: string) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      const api = authApi();
      await api.delete(`/api/v1/documents/${docId}`);
      toast.success("Document deleted");
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch {
      toast.error("Failed to delete document");
    }
  };

  const handleLogout = () => {
    Cookies.remove("access_token", { path: "/" });
    router.push("/login");
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case "ready":
        return <span className="badge-ready"><CheckCircle className="w-3 h-3" /> Ready</span>;
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
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-brand-400 animate-spin" />
          <p className="text-slate-400">Loading your knowledge base…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex">
      <aside className="w-72 flex-shrink-0 border-r border-surface-border bg-surface-card flex flex-col">
        <div className="p-6 border-b border-surface-border">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-slate-100">RAG Assistant</span>
          </div>
          <p className="text-xs text-slate-500 mt-1 truncate">{userEmail}</p>
        </div>

        <nav className="p-4 space-y-1 flex-1 overflow-y-auto">
          <button
            onClick={() => setView("upload")}
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
            onClick={() => { setView("chat"); setActiveConvId(null); }}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
              view === "chat" && !activeConvId
                ? "bg-brand-600/20 text-brand-300 border border-brand-500/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-surface-hover"
            }`}
          >
            <Plus className="w-4 h-4" />
            New chat
          </button>

          {conversations.length > 0 && (
            <div className="pt-4">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2">
                Recent chats
              </p>
              {conversations.slice(0, 15).map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => { setActiveConvId(conv.id); setView("chat"); }}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-all text-left ${
                    activeConvId === conv.id
                      ? "bg-brand-600/20 text-brand-300 border border-brand-500/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-surface-hover"
                  }`}
                >
                  <MessageSquare className="w-4 h-4 flex-shrink-0" />
                  <span className="truncate">{conv.title}</span>
                </button>
              ))}
            </div>
          )}
        </nav>

        <div className="p-4 border-t border-surface-border">
          <button onClick={handleLogout} className="btn-ghost w-full justify-start text-sm">
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {view === "upload" ? (
          <div className="flex-1 overflow-y-auto p-8">
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
                <input {...getInputProps()} id="file-upload" />
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

              {documents.length === 0 ? (
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
                      </div>
                      <div className="flex items-center gap-3">
                        {statusBadge(doc.status)}
                        {doc.status === "ready" && (
                          <button
                            onClick={() => { setView("chat"); setActiveConvId(null); }}
                            className="opacity-0 group-hover:opacity-100 btn-ghost text-xs py-1.5 transition-opacity"
                          >
                            Ask <ChevronRight className="w-3 h-3" />
                          </button>
                        )}
                        <button
                          onClick={() => deleteDocument(doc.id, doc.original_name)}
                          className="opacity-0 group-hover:opacity-100 btn-danger text-xs py-1.5 transition-opacity"
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
              fetchData();
            }}
          />
        )}
      </main>
    </div>
  );
}
