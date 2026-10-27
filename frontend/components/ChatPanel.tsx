"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Send, Loader2, BookOpen, ChevronDown, ChevronUp, Square, Copy, RefreshCw, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import toast from "react-hot-toast";
import { authApi, getApiErrorMessage, handleUnauthorized, type Message, type Citation } from "@/lib/api";
import { createSseParser, applyStreamEvent, emptyStreamState, type StreamState } from "@/lib/stream";
import CitationPanel from "@/components/CitationPanel";
import clsx from "clsx";

interface ChatPanelProps {
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
}

interface LocalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  streaming?: boolean;
}

export default function ChatPanel({ conversationId, onConversationCreated }: ChatPanelProps) {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streamStatus, setStreamStatus] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<{ citation: Citation; index: number } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  // Ref mirror of conversationId: sendMessage's done-handler must
  // use the value at send time, not a stale closure.
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  const scrollToBottom = () => {
    // jsdom (and some embedded browsers) lack scrollIntoView;
    // scrolling is a nicety, never a reason to crash the chat.
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Stop any in-flight stream if the panel unmounts (e.g. user
  // switches view). The backend persists the partial assistant
  // message in its generator finally-block (chat.py), so stopping
  // here does not lose the streamed text server-side.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => undefined);
    };
  }, []);

  const loadHistory = useCallback(async (convId: string) => {
    setLoadingHistory(true);
    try {
      const res = await authApi().get(`/api/v1/chat/conversations/${convId}`);
      const conv = res.data;
      setMessages(
        conv.messages.map((m: Message) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          citations: m.citations || [],
        }))
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (conversationId) {
      loadHistory(conversationId);
    } else {
      setMessages([]);
    }
  }, [conversationId, loadHistory]);

  const stopGeneration = useCallback(() => {
    // AbortController rejects the pending reader.read(); we also
    // cancel the reader so the network stream is torn down now,
    // not when the next chunk arrives.
    abortRef.current?.abort();
    readerRef.current?.cancel().catch(() => undefined);
  }, []);

  const sendMessage = useCallback(async (overrideQuestion?: string) => {
    const question = (overrideQuestion ?? input).trim();
    if (!question || sending) return;

    const userMsg: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      citations: [],
    };
    const assistantPlaceholder: LocalMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      citations: [],
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
    setInput("");
    setSending(true);
    setStreamStatus("");
    setStreamFailed(false);

    const controller = new AbortController();
    abortRef.current = controller;
    let stopped = false;

    try {
      // Phase E: httpOnly cookie is sent automatically by the
      // browser on this same-origin request; no token in JS.
      // fetch (not axios) is used deliberately for streaming:
      // axios cannot expose a ReadableStream body for SSE.
      const res = await fetch(`/api/v1/chat/stream`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: conversationIdRef.current || null,
        }),
        signal: controller.signal,
      });

      if (res.status === 401) {
        handleUnauthorized();
        throw new Error("Session expired. Please sign in again.");
      }
      if (!res.ok) {
        throw new Error("Stream request failed");
      }

      const reader = res.body?.getReader();
      readerRef.current = reader ?? null;
      const decoder = new TextDecoder();
      let state: StreamState = emptyStreamState();

      const applyToLast = (next: StreamState) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last) {
            updated[updated.length - 1] = {
              ...last,
              content: next.content,
              citations: next.citations,
              streaming: !next.done,
            };
          }
          return updated;
        });
      };

      if (reader) {
        const parser = createSseParser((event) => {
          state = applyStreamEvent(state, event);
          if (event.type === "status") setStreamStatus(event.status);
          if (event.type === "error") toast.error(event.error);
          if (event.type === "done") {
            setStreamStatus("");
            if (event.conversation_id && !conversationIdRef.current) {
              onConversationCreated(event.conversation_id);
            }
          }
          applyToLast(state);
        });
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            parser.feed(decoder.decode(value, { stream: true }));
          }
          parser.flush();
        } finally {
          readerRef.current = null;
        }
      }

      // Normal completion (or empty body): mark not-streaming and
      // keep whatever was streamed. Unlike the pre-Phase-F code,
      // a failed/aborted stream no longer deletes the partial
      // assistant message — the backend persists it too.
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.streaming) {
          updated[updated.length - 1] = { ...last, streaming: false };
        }
        return updated;
      });
    } catch (err) {
      if (controller.signal.aborted) {
        stopped = true;
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.streaming) {
            updated[updated.length - 1] = { ...last, streaming: false };
          }
          return updated;
        });
        toast.success("Generation stopped. Partial answer kept.");
      } else {
        // Keep the partial assistant message (if any) instead of
        // deleting it, and offer Retry. The backend's finally-block
        // persists the same partial text server-side.
        setStreamFailed(true);
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.streaming) {
            updated[updated.length - 1] = { ...last, streaming: false };
          }
          return updated;
        });
        toast.error(getApiErrorMessage(err));
      }
    } finally {
      setSending(false);
      setStreamStatus("");
      abortRef.current = null;
      if (stopped) textareaRef.current?.focus();
    }
  }, [input, sending, onConversationCreated]);

  const retryLast = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) void sendMessage(lastUser.content);
  }, [messages, sendMessage]);

  const regenerateLast = useCallback(() => {
    // Regenerate is a fresh re-ask of the last user question (the
    // backend has no replace-message endpoint), so it appears as
    // a new turn. Documented in docs/phase-f-report.md.
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) void sendMessage(lastUser.content);
  }, [messages, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
    }
  };

  const lastMessage = messages[messages.length - 1];
  const canRegenerate = !sending && lastMessage?.role === "assistant" && !!lastMessage.content;

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 space-y-6" role="log" aria-live="polite" aria-label="Chat messages">
        {loadingHistory ? (
          <div className="flex justify-center py-12" role="status" aria-label="Loading conversation">
            <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-brand-600/10 border border-brand-500/20 flex items-center justify-center mb-6">
              <BookOpen className="w-8 h-8 text-brand-400" />
            </div>
            <h2 className="text-xl font-semibold text-slate-200 mb-2">Ask your documents anything</h2>
            <p className="text-slate-500 max-w-sm">
              Start a conversation. The AI will retrieve relevant chunks from your documents and cite its sources.
            </p>
            <div className="mt-8 grid grid-cols-1 gap-3 w-full max-w-md">
              {[
                "Summarise the key findings in this document",
                "What are the main risks mentioned?",
                "List all action items or recommendations",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => setInput(suggestion)}
                  className="card-hover px-5 py-3 text-sm text-slate-400 hover:text-slate-200 text-left transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onSelectCitation={(citation, index) => setSelectedCitation({ citation, index })}
              onCopy={() => {
                if (navigator.clipboard) {
                  navigator.clipboard.writeText(msg.content).then(
                    () => toast.success("Answer copied"),
                    () => toast.error("Could not copy answer")
                  );
                }
              }}
            />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-surface-border p-4 bg-surface-card">
        <div className="max-w-4xl mx-auto">
          <div className={clsx(
            "flex gap-3 items-end p-3 rounded-2xl border transition-all",
            sending
              ? "border-brand-500/30 bg-brand-600/5"
              : "border-surface-border bg-surface hover:border-brand-500/40 focus-within:border-brand-500/60"
          )}>
            <textarea
              ref={textareaRef}
              id="chat-input"
              aria-label="Ask a question about your documents"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your documents… (Enter to send, Shift+Enter for new line)"
              rows={1}
              disabled={sending}
              className="flex-1 bg-transparent text-slate-100 placeholder-slate-500 text-sm resize-none focus:outline-none leading-relaxed"
              style={{ maxHeight: "200px" }}
            />
            {sending ? (
              <button
                type="button"
                onClick={stopGeneration}
                aria-label="Stop generation"
                className="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all bg-red-600/20 hover:bg-red-600/30 text-red-300 border border-red-500/30"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                id="chat-send"
                aria-label="Send message"
                onClick={() => void sendMessage()}
                disabled={!input.trim()}
                className={clsx(
                  "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all",
                  input.trim()
                    ? "bg-brand-600 hover:bg-brand-500 text-white shadow-lg shadow-brand-600/30"
                    : "bg-surface-border text-slate-500 cursor-not-allowed"
                )}
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className="flex items-center justify-center gap-2 mt-2">
            {sending && streamStatus && (
              <p className="text-xs text-slate-500 text-center" role="status">
                {streamStatus}…
              </p>
            )}
            {!sending && streamFailed && (
              <button type="button" onClick={retryLast} className="btn-ghost text-xs py-1">
                <RefreshCw className="w-3 h-3" /> Retry last message
              </button>
            )}
            {!sending && canRegenerate && (
              <button type="button" onClick={regenerateLast} aria-label="Regenerate last answer" className="btn-ghost text-xs py-1">
                <RotateCcw className="w-3 h-3" /> Regenerate
              </button>
            )}
          </div>
          <p className="text-xs text-slate-600 text-center mt-2">
            Answers are grounded in your documents
          </p>
        </div>
      </div>

      {selectedCitation && (
        <CitationPanel
          citation={selectedCitation.citation}
          index={selectedCitation.index}
          onClose={() => setSelectedCitation(null)}
        />
      )}
    </div>
  );
}

function MessageBubble({
  message,
  onSelectCitation,
  onCopy,
}: {
  message: LocalMessage;
  onSelectCitation: (citation: Citation, index: number) => void;
  onCopy: () => void;
}) {
  const [showCitations, setShowCitations] = useState(false);
  const isUser = message.role === "user";

  return (
    <div className={clsx("flex animate-fade-in", isUser ? "justify-end" : "justify-start")}>
      <div className={clsx("max-w-3xl", isUser ? "message-user" : "message-assistant")}>
        {isUser ? (
          <p className="text-sm leading-relaxed">{message.content}</p>
        ) : (
          <div>
            {message.streaming && !message.content ? (
              <div className="flex gap-1.5 py-1" role="status" aria-label="Generating answer">
                <div className="typing-dot" />
                <div className="typing-dot" />
                <div className="typing-dot" />
              </div>
            ) : (
              <div className="prose-chat text-sm">
                {/* rehype-sanitize: embedded HTML in model output is
                    stripped, not executed. Raw HTML rendering is
                    deliberately not enabled anywhere in this app. */}
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            )}

            {!isUser && message.content && !message.streaming && (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  onClick={onCopy}
                  aria-label="Copy answer"
                  className="btn-ghost text-xs py-1"
                >
                  <Copy className="w-3 h-3" /> Copy
                </button>
              </div>
            )}

            {message.citations.length > 0 && (
              <div className="mt-4 pt-3 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setShowCitations(!showCitations)}
                  aria-expanded={showCitations}
                  aria-label={`${showCitations ? "Hide" : "Show"} ${message.citations.length} sources`}
                  className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-300 transition-colors mb-2"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  {message.citations.length} source{message.citations.length > 1 ? "s" : ""}
                  {showCitations ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showCitations && (
                  <div className="space-y-2">
                    {message.citations.map((citation, idx) => (
                      <button
                        key={citation.chunk_id || idx}
                        type="button"
                        onClick={() => onSelectCitation(citation, idx)}
                        aria-label={`Open source ${idx + 1}: ${citation.document_name}`}
                        className="citation-pill flex-col items-start gap-1.5 w-full text-left"
                      >
                        <div className="flex items-center gap-2 w-full">
                          <span className="w-5 h-5 rounded-md bg-brand-600/20 text-brand-300 text-xs flex items-center justify-center font-mono flex-shrink-0">
                            {idx + 1}
                          </span>
                          <span className="font-medium text-brand-300 truncate">{citation.document_name}</span>
                          <span className="ml-auto text-slate-500 text-xs flex-shrink-0">
                            chunk {citation.chunk_index}
                            {citation.page != null ? ` · p. ${citation.page}` : ""}
                            {citation.section ? ` · ${citation.section}` : ""} · {(citation.score * 100).toFixed(0)}% match
                          </span>
                        </div>
                        <p className="text-slate-400 text-xs leading-relaxed pl-7 line-clamp-2 text-left">
                          {citation.snippet}
                        </p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
