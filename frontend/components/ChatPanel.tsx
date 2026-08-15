"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Send, Loader2, BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import toast from "react-hot-toast";
import { authApi, type Message, type Citation } from "@/lib/api";
import Cookies from "js-cookie";
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
  const [loadingHistory, setLoadingHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const loadHistory = useCallback(async (convId: string) => {
    setLoadingHistory(true);
    try {
      const api = authApi();
      const res = await api.get(`/api/v1/chat/conversations/${convId}`);
      const conv = res.data;
      setMessages(
        conv.messages.map((m: Message) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: m.content,
          citations: m.citations || [],
        }))
      );
    } catch {
      toast.error("Failed to load conversation");
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

  const sendMessage = async () => {
    const question = input.trim();
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

    try {
      const token = Cookies.get("access_token");

      const res = await fetch(`/api/v1/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question,
          conversation_id: conversationId || null,
        }),
      });

      if (!res.ok) {
        throw new Error("Stream request failed");
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data: ")) {
              try {
                const data = JSON.parse(trimmed.slice(6));
                if (data.token) {
                  accumulated += data.token;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.streaming) {
                      updated[updated.length - 1] = {
                        ...last,
                        content: accumulated,
                      };
                    }
                    return updated;
                  });
                }
                if (data.citations) {
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last) {
                      updated[updated.length - 1] = {
                        ...last,
                        citations: data.citations,
                      };
                    }
                    return updated;
                  });
                }
                if (data.done && data.conversation_id && !conversationId) {
                  onConversationCreated(data.conversation_id);
                }
              } catch {
              }
            }
          }
        }
      }

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last.streaming) {
          updated[updated.length - 1] = { ...last, streaming: false };
        }
        return updated;
      });
    } catch (err) {
      toast.error("Failed to get a response. Please try again.");
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
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

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {loadingHistory ? (
          <div className="flex justify-center py-12">
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
            <MessageBubble key={msg.id} message={msg} />
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
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your documents… (Enter to send, Shift+Enter for new line)"
              rows={1}
              disabled={sending}
              className="flex-1 bg-transparent text-slate-100 placeholder-slate-500 text-sm resize-none focus:outline-none leading-relaxed"
              style={{ maxHeight: "200px" }}
            />
            <button
              id="chat-send"
              onClick={sendMessage}
              disabled={!input.trim() || sending}
              className={clsx(
                "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all",
                input.trim() && !sending
                  ? "bg-brand-600 hover:bg-brand-500 text-white shadow-lg shadow-brand-600/30"
                  : "bg-surface-border text-slate-500 cursor-not-allowed"
              )}
            >
              {sending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
          <p className="text-xs text-slate-600 text-center mt-2">
            Answers are grounded in your documents · GPT-4o + Qdrant
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: LocalMessage }) {
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
              <div className="flex gap-1.5 py-1">
                <div className="typing-dot" />
                <div className="typing-dot" />
                <div className="typing-dot" />
              </div>
            ) : (
              <div className="prose-chat text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            )}

            {message.citations.length > 0 && (
              <div className="mt-4 pt-3 border-t border-surface-border">
                <button
                  onClick={() => setShowCitations(!showCitations)}
                  className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-300 transition-colors mb-2"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  {message.citations.length} source{message.citations.length > 1 ? "s" : ""}
                  {showCitations ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showCitations && (
                  <div className="space-y-2">
                    {message.citations.map((citation, idx) => (
                      <div key={idx} className="citation-pill flex-col items-start gap-1.5 w-full">
                        <div className="flex items-center gap-2 w-full">
                          <span className="w-5 h-5 rounded-md bg-brand-600/20 text-brand-300 text-xs flex items-center justify-center font-mono flex-shrink-0">
                            {idx + 1}
                          </span>
                          <span className="font-medium text-brand-300 truncate">{citation.document_name}</span>
                          <span className="ml-auto text-slate-500 text-xs flex-shrink-0">
                            chunk {citation.chunk_index} · {(citation.score * 100).toFixed(0)}% match
                          </span>
                        </div>
                        <p className="text-slate-400 text-xs leading-relaxed pl-7 line-clamp-2">
                          {citation.snippet}
                        </p>
                      </div>
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
