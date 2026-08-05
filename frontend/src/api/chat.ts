import { api, apiUrl, getStoredTokens, refreshTokens } from "./client";

export interface Conversation {
  id: number;
  title: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ConversationDetail {
  id: number;
  title: string;
  messages: ChatMessage[];
}

export const listConversations = () => api<Conversation[]>("/api/v1/chat/conversations");
export const createConversation = () =>
  api<ConversationDetail>("/api/v1/chat/conversations", { method: "POST" });
export const getConversation = (id: number) =>
  api<ConversationDetail>(`/api/v1/chat/conversations/${id}`);
export const deleteConversation = (id: number) =>
  api<void>(`/api/v1/chat/conversations/${id}`, { method: "DELETE" });

/**
 * Send a message and stream the assistant's reply token by token.
 * Calls onChunk for each text delta; resolves on the done event.
 * Throws with a friendly message if the server streams an error.
 */
export async function streamMessage(
  conversationId: number,
  content: string,
  onChunk: (text: string) => void,
): Promise<void> {
  const url = apiUrl(`/api/v1/chat/conversations/${conversationId}/messages`);
  const doFetch = () => {
    const tokens = getStoredTokens();
    return fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {}),
      },
      body: JSON.stringify({ content }),
    });
  };

  let resp = await doFetch();
  if (resp.status === 401) {
    const fresh = await refreshTokens();
    if (fresh) resp = await doFetch();
  }
  if (!resp.ok || !resp.body) {
    let detail = "Could not send message.";
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // Parse the SSE stream: events are separated by blank lines.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const evt of events) {
      let eventType = "message";
      let data = "";
      for (const line of evt.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const parsed = JSON.parse(data);
      if (eventType === "error") throw new Error(parsed.message ?? "The tutor is unavailable.");
      if (eventType === "done") return;
      if (parsed.text) onChunk(parsed.text);
    }
  }
}
