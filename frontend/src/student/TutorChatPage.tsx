import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  streamMessage,
  type ChatMessage,
} from "../api/chat";

export default function TutorChatPage() {
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: listConversations });
  const [activeId, setActiveId] = useState<number | null>(null);

  const conversation = useQuery({
    queryKey: ["conversation", activeId],
    queryFn: () => getConversation(activeId!),
    enabled: activeId !== null,
  });

  // Local view of the transcript so we can append streaming tokens live.
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (conversation.data) setMessages(conversation.data.messages);
  }, [conversation.data]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, streaming]);

  const newChat = useMutation({
    mutationFn: createConversation,
    onSuccess: (convo) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setActiveId(convo.id);
      setMessages([]);
    },
  });

  const removeChat = useMutation({
    mutationFn: (id: number) => deleteConversation(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    },
  });

  async function onSend(e: FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy) return;
    setError(null);

    let convoId = activeId;
    if (convoId === null) {
      const convo = await createConversation();
      convoId = convo.id;
      setActiveId(convo.id);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }

    const text = input.trim();
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), role: "user", content: text, created_at: "" },
    ]);
    setBusy(true);
    setStreaming("");
    let acc = "";
    try {
      await streamMessage(convoId, text, (chunk) => {
        acc += chunk;
        setStreaming(acc);
      });
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, role: "assistant", content: acc, created_at: "" },
      ]);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setStreaming("");
      setBusy(false);
    }
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] gap-4">
      {/* Conversation list */}
      <aside className="w-56 shrink-0 overflow-y-auto rounded-lg border bg-white p-2">
        <button
          onClick={() => newChat.mutate()}
          className="mb-2 w-full rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700"
        >
          + New chat
        </button>
        <ul className="space-y-1">
          {conversations.data?.map((c) => (
            <li key={c.id} className="group flex items-center gap-1">
              <button
                onClick={() => setActiveId(c.id)}
                className={`flex-1 truncate rounded px-2 py-1.5 text-left text-sm ${
                  activeId === c.id ? "bg-blue-50 text-blue-700" : "hover:bg-slate-50"
                }`}
              >
                {c.title}
              </button>
              <button
                onClick={() => removeChat.mutate(c.id)}
                className="hidden text-xs text-slate-400 hover:text-red-500 group-hover:block"
                title="Delete"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Chat panel */}
      <section className="flex flex-1 flex-col rounded-lg border bg-white">
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && !streaming && (
            <div className="mt-10 text-center text-slate-400">
              <p className="text-lg">Ask your AI tutor anything</p>
              <p className="mt-1 text-sm">
                Concepts, revision plans, or how to approach a tricky topic.
                <br />
                It won't do your homework for you — it helps you learn.
              </p>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} role={m.role} content={m.content} />
          ))}
          {streaming && <MessageBubble role="assistant" content={streaming} />}
          {busy && !streaming && <div className="text-sm text-slate-400">Tutor is thinking…</div>}
        </div>

        {error && <p className="border-t bg-red-50 px-4 py-2 text-sm text-red-600">{error}</p>}
        <form onSubmit={onSend} className="flex gap-2 border-t p-3">
          <input
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="Ask a question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </section>
    </div>
  );
}

function MessageBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
          isUser ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-800"
        }`}
      >
        {content}
      </div>
    </div>
  );
}
