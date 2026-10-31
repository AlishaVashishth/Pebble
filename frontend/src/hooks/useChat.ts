import { useState, useEffect, useRef, useCallback } from 'react';
import {
  ChatMessage,
  ChatSession,
  loadChatSessions,
  saveChatSessions,
  createChatSession,
  askPebble,
  formatAskResponse,
} from '../lib/chat.ts';
import { getToken } from '../lib/api.ts';
import {
  fetchConversations,
  createConversation,
  fetchConversationDetail,
  createConversationMessage,
  deleteConversationApi,
  updateMessageMetaApi,
} from '../lib/conversations.ts';
import {
  PebbleLanguage,
  getStoredLanguage,
  setStoredLanguage,
} from '../components/Home/LanguageChips.tsx';
import { getVideoJobStatus } from '../lib/video.ts';

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function useChat() {
  // Always initialize with a fresh, empty draft session for a clean welcome state on every visit/login
  const [initialDraft] = useState<ChatSession>(() => createChatSession('New conversation'));
  const [sessions, setSessions] = useState<ChatSession[]>([initialDraft]);
  const [activeSessionId, setActiveSessionId] = useState<string>(initialDraft.id);
  const [isStreaming, setIsStreaming] = useState(false);
  const [deepThink, setDeepThink] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const activeSessionIdRef = useRef(activeSessionId);
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const activeVideoPollsRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  // Update message metadata (e.g. when video generation completes)
  const updateMessageMeta = useCallback(
    async (messageId: string, metaUpdates: Record<string, any>, targetSessionId?: string) => {
      let resolvedConvId: string | null = targetSessionId || null;
      let resolvedMsgId: string = messageId;

      setSessions((prev) =>
        prev.map((s) => {
          const hasMsg = s.messages.some(
            (m) =>
              m.id === messageId ||
              (m.meta?.video_job_id &&
                metaUpdates.video_job_id &&
                m.meta.video_job_id === metaUpdates.video_job_id)
          );
          if (!hasMsg && s.id !== activeSessionIdRef.current && s.id !== targetSessionId) {
            return s;
          }

          if (!resolvedConvId && (s.id === targetSessionId || hasMsg)) {
            resolvedConvId = s.id;
          }

          return {
            ...s,
            messages: s.messages.map((m) => {
              const isMatch =
                m.id === messageId ||
                (m.meta?.video_job_id &&
                  metaUpdates.video_job_id &&
                  m.meta.video_job_id === metaUpdates.video_job_id);
              if (isMatch) {
                if (UUID_REGEX.test(m.id)) {
                  resolvedMsgId = m.id;
                }
                return { ...m, meta: { ...(m.meta || {}), ...metaUpdates } };
              }
              return m;
            }),
            updatedAt: Date.now(),
          };
        })
      );

      const convIdToUse = resolvedConvId || activeSessionIdRef.current;
      if (UUID_REGEX.test(convIdToUse) && UUID_REGEX.test(resolvedMsgId) && getToken()) {
        try {
          await updateMessageMetaApi(convIdToUse, resolvedMsgId, metaUpdates);
        } catch (err) {
          console.warn('Failed to update message meta on API', err);
        }
      }
    },
    []
  );

  const registerVideoJobPolling = useCallback(
    (jobId: string, convId: string, msgId: string) => {
      if (!jobId || activeVideoPollsRef.current.has(jobId)) return;

      const pollStartTime = Date.now();
      const interval = setInterval(async () => {
        // Stop after 30 minutes
        if (Date.now() - pollStartTime > 30 * 60 * 1000) {
          clearInterval(interval);
          activeVideoPollsRef.current.delete(jobId);
          updateMessageMeta(
            msgId,
            { video_status: 'failed', video_error: 'Video generation timed out' },
            convId
          );
          return;
        }

        try {
          const statusData = await getVideoJobStatus(jobId);
          if (statusData.status === 'completed') {
            clearInterval(interval);
            activeVideoPollsRef.current.delete(jobId);
            const finalUrl = statusData.videoUrl || statusData.video_url;
            if (finalUrl) {
              updateMessageMeta(
                msgId,
                { video_url: finalUrl, video_status: 'completed', video_job_id: jobId },
                convId
              );
            }
          } else if (statusData.status === 'failed') {
            clearInterval(interval);
            activeVideoPollsRef.current.delete(jobId);
            updateMessageMeta(
              msgId,
              {
                video_status: 'failed',
                video_error: statusData.error || 'Video rendering failed',
                video_job_id: jobId,
              },
              convId
            );
          }
        } catch (err) {
          // Continue polling on transient errors
        }
      }, 3000);

      activeVideoPollsRef.current.set(jobId, interval);
    },
    [updateMessageMeta]
  );

  useEffect(() => {
    return () => {
      activeVideoPollsRef.current.forEach((interval) => clearInterval(interval));
      activeVideoPollsRef.current.clear();
    };
  }, []);

  // Helper to normalize backend messages to ChatMessage[]
  const mapApiMessages = useCallback((apiMessages: any[]): ChatMessage[] => {
    const msgs: ChatMessage[] = (apiMessages || []).map((m) => ({
      id: m.id,
      role: m.role as 'user' | 'assistant',
      content: m.content,
      timestamp: new Date(m.created_at).getTime(),
      meta: m.meta || undefined,
      conversationId: m.conversation_id,
    }));

    // Backfill userPrompt if missing
    for (let i = 0; i < msgs.length; i++) {
      if (msgs[i].role === 'assistant' && i > 0 && msgs[i - 1].role === 'user') {
        if (!msgs[i].meta) msgs[i].meta = {};
        if (!msgs[i].meta.userPrompt) {
          msgs[i].meta.userPrompt = msgs[i - 1].content;
        }
      }
    }
    return msgs;
  }, []);

  // On mount: load user conversations from backend (newest first)
  useEffect(() => {
    let isCancelled = false;

    async function loadRemoteConversations() {
      const token = getToken();
      if (!token) return;

      try {
        const apiList = await fetchConversations(50, 0);
        if (isCancelled) return;

        if (apiList && apiList.length > 0) {
          const remoteSessions: ChatSession[] = apiList.map((c) => ({
            id: c.id,
            title: c.title || 'New conversation',
            createdAt: new Date(c.created_at).getTime(),
            updatedAt: new Date(c.updated_at).getTime(),
            messages: [],
          }));

          // Keep current fresh draft active at top; list remote sessions in sidebar without auto-selecting
          setSessions((prev) => {
            const currentDraft =
              prev.find((s) => s.messages.length === 0 && !UUID_REGEX.test(s.id)) ||
              createChatSession('New conversation');
            return [currentDraft, ...remoteSessions];
          });
        } else {
          // No remote conversations: ensure single empty draft
          const emptyDraft = createChatSession('New conversation');
          setSessions([emptyDraft]);
          setActiveSessionId(emptyDraft.id);
        }
      } catch (err) {
        console.warn('Failed to load conversations from API, using fallback', err);
      }
    }

    loadRemoteConversations();

    return () => {
      isCancelled = true;
    };
  }, [mapApiMessages]);

  // Ensure active session exists
  useEffect(() => {
    if (!sessions.some((s) => s.id === activeSessionId)) {
      setActiveSessionId(sessions[0]?.id ?? '');
    }
  }, [sessions, activeSessionId]);

  // Fallback: persist sessions to localStorage with a small debounce without deleting existing chats
  useEffect(() => {
    const id = window.setTimeout(
      () => saveChatSessions(sessions),
      isStreaming ? 1000 : 150
    );
    return () => window.clearTimeout(id);
  }, [sessions, isStreaming]);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? sessions[0];

  const cancelRequest = useCallback(() => {
    const controller = abortControllerRef.current;
    if (controller) {
      abortControllerRef.current = null;
      controller.abort();
      setIsStreaming(false);
    }
  }, []);

  // Create a conversation only locally; create in DB only when first message is sent
  const createNewChat = useCallback(() => {
    cancelRequest();

    setSessions((prev) => {
      const existingEmpty = prev.find((s) => s.messages.length === 0);
      if (existingEmpty) {
        setActiveSessionId(existingEmpty.id);
        return prev;
      }
      const newSession = createChatSession('New conversation');
      setActiveSessionId(newSession.id);
      return [newSession, ...prev];
    });
  }, [cancelRequest]);

  // Select session and load its messages if not already loaded or to refresh
  const selectSession = useCallback(
    async (id: string) => {
      cancelRequest();
      setActiveSessionId(id);

      if (UUID_REGEX.test(id) && getToken()) {
        try {
          const detail = await fetchConversationDetail(id);
          const msgs = mapApiMessages(detail.messages);

          setSessions((prev) =>
            prev.map((s) =>
              s.id === id
                ? {
                    ...s,
                    title: detail.title || s.title,
                    updatedAt: new Date(detail.updated_at).getTime(),
                    messages: msgs,
                  }
                : s
            )
          );

          msgs.forEach((m) => {
            if (m.meta?.video_job_id && !m.meta?.video_url && m.meta?.video_status !== 'failed') {
              registerVideoJobPolling(m.meta.video_job_id, id, m.id);
            }
          });
        } catch (err) {
          console.warn('Failed to load conversation messages from API', err);
        }
      }
    },
    [cancelRequest, mapApiMessages]
  );

  // Delete conversation: call API and update local state
  const deleteSession = useCallback(
    (id: string) => {
      if (id === activeSessionId) {
        cancelRequest();
      }

      setSessions((prev) => {
        const filtered = prev.filter((s) => s.id !== id);
        return filtered.length > 0 ? filtered : [createChatSession('New conversation')];
      });

      if (id === activeSessionId) {
        const nextSession = sessions.find((s) => s.id !== id);
        setActiveSessionId(nextSession?.id ?? '');
      }

      if (UUID_REGEX.test(id) && getToken()) {
        deleteConversationApi(id).catch((err) => {
          console.warn('Failed to delete conversation on API', err);
        });
      }
    },
    [activeSessionId, cancelRequest, sessions]
  );

  // Clear current chat: delete on backend if UUID, reset to clean local state
  const clearCurrentChat = useCallback(() => {
    cancelRequest();

    const oldId = activeSessionId;
    const freshSession = createChatSession('New conversation');
    setActiveSessionId(freshSession.id);

    setSessions((prev) => prev.map((s) => (s.id === oldId ? freshSession : s)));

    if (UUID_REGEX.test(oldId) && getToken()) {
      deleteConversationApi(oldId).catch((err) => {
        console.warn('Failed to delete cleared conversation on API', err);
      });
    }
  }, [activeSessionId, cancelRequest]);

  const stopStreaming = cancelRequest;

  // Send message
  const sendMessage = useCallback(
    async (text: string, languageOverride?: PebbleLanguage) => {
      const trimmed = text.trim();
      if (!trimmed || abortControllerRef.current) return;

      const currentSession = activeSession;
      if (!currentSession) return;

      const preferredLang: PebbleLanguage = languageOverride || getStoredLanguage();
      if (languageOverride) {
        setStoredLanguage(languageOverride);
      }

      const now = Date.now();
      const currentTitle =
        currentSession.messages.length === 0
          ? trimmed.slice(0, 36) + (trimmed.length > 36 ? '...' : '')
          : currentSession.title;

      let effectiveSessionId = currentSession.id;
      const isInitialUuid = UUID_REGEX.test(effectiveSessionId);

      // Create conversation thread on API if this is an unsaved local draft
      let createdPromise: Promise<string | null> | null = null;
      if (!isInitialUuid && getToken()) {
        createdPromise = createConversation(currentTitle)
          .then((conv) => {
            effectiveSessionId = conv.id;
            setActiveSessionId(conv.id);
            setSessions((prev) =>
              prev.map((s) =>
                s.id === currentSession.id
                  ? {
                      ...s,
                      id: conv.id,
                      title: conv.title || currentTitle,
                      updatedAt: new Date(conv.updated_at).getTime(),
                    }
                  : s
              )
            );
            return conv.id;
          })
          .catch((err) => {
            console.warn('Failed to create conversation on API, falling back to local ID', err);
            return null;
          });
      }

      const localUserMsgId = `msg_${now}_u`;
      const localAssistantMsgId = `msg_${now}_a`;

      const userMsg: ChatMessage = {
        id: localUserMsgId,
        role: 'user',
        content: trimmed,
        timestamp: now,
        conversationId: effectiveSessionId,
      };

      const initialAssistantMsg: ChatMessage = {
        id: localAssistantMsgId,
        role: 'assistant',
        content: '',
        timestamp: now,
        meta: { userPrompt: trimmed, language: preferredLang },
        conversationId: effectiveSessionId,
      };

      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentSession.id || s.id === effectiveSessionId
            ? {
                ...s,
                title: currentTitle,
                updatedAt: now,
                messages: [...s.messages, userMsg, initialAssistantMsg],
              }
            : s
        )
      );

      // Persist user message to API asynchronously once conversation UUID is available
      const persistUserMsg = async () => {
        let convId = effectiveSessionId;
        if (createdPromise) {
          const res = await createdPromise;
          if (res) convId = res;
        }
        if (UUID_REGEX.test(convId) && getToken()) {
          try {
            const saved = await createConversationMessage(convId, {
              role: 'user',
              content: trimmed,
            });
            setSessions((prev) =>
              prev.map((s) =>
                s.id === convId
                  ? {
                      ...s,
                      messages: s.messages.map((m) =>
                        m.id === localUserMsgId ? { ...m, id: saved.id } : m
                      ),
                    }
                  : s
              )
            );
          } catch (err) {
            console.warn('Failed to persist user message to API', err);
          }
        }
      };

      persistUserMsg();

      const controller = new AbortController();
      abortControllerRef.current = controller;
      setIsStreaming(true);

      const setReply = (content: string) => {
        setSessions((prev) =>
          prev.map((s) =>
            s.id === currentSession.id || s.id === effectiveSessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === localAssistantMsgId ? { ...m, content } : m
                  ),
                  updatedAt: Date.now(),
                }
              : s
          )
        );
      };

      try {
        const response = await askPebble(trimmed, preferredLang, controller.signal);
        const reply = formatAskResponse(response);

        if (!controller.signal.aborted) {
          const finalMeta = {
            ...response,
            userPrompt: trimmed,
            language: preferredLang,
            video_url: response.video_url || null,
            video_job_id: response.video_job_id || null,
            video_status:
              response.video_status ||
              (response.video_url
                ? 'completed'
                : response.video_job_id
                ? 'processing'
                : null),
          };

          let convId = effectiveSessionId;
          if (createdPromise) {
            const res = await createdPromise;
            if (res) convId = res;
          }

          setSessions((prev) =>
            prev.map((s) =>
              s.id === convId || s.id === currentSession.id
                ? {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === localAssistantMsgId
                        ? { ...m, content: String(reply), meta: finalMeta }
                        : m
                    ),
                    updatedAt: Date.now(),
                  }
                : s
            )
          );

          // If a new video job is processing, register background polling
          if (
            response.video_job_id &&
            response.video_status !== 'completed' &&
            !response.video_url
          ) {
            registerVideoJobPolling(response.video_job_id, convId, localAssistantMsgId);
          }

          // Save assistant message to API
          if (UUID_REGEX.test(convId) && getToken()) {
            try {
              const saved = await createConversationMessage(convId, {
                role: 'assistant',
                content: String(reply),
                meta: finalMeta,
              });
              setSessions((prev) =>
                prev.map((s) =>
                  s.id === convId
                    ? {
                        ...s,
                        messages: s.messages.map((m) =>
                          m.id === localAssistantMsgId ? { ...m, id: saved.id } : m
                        ),
                      }
                    : s
                )
              );
            } catch (err) {
              console.warn('Failed to persist assistant message to API', err);
            }
          }
        }
      } catch (err) {
        if (controller.signal.aborted) {
          setReply('*Stopped.*');
        } else {
          setReply(
            `Warning: ${err instanceof Error ? err.message : 'Something went wrong'}`
          );
        }
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [activeSession, registerVideoJobPolling]
  );

  // Listen for language chip re-ask event
  useEffect(() => {
    const handleReask = (e: Event) => {
      const ce = e as CustomEvent<{ text: string; language?: PebbleLanguage }>;
      if (ce.detail?.text) {
        sendMessage(ce.detail.text, ce.detail.language);
      }
    };
    window.addEventListener('pebble:reask', handleReask);
    return () => window.removeEventListener('pebble:reask', handleReask);
  }, [sendMessage]);

  return {
    sessions,
    activeSession,
    activeSessionId,
    isStreaming,
    deepThink,
    setDeepThink,
    sendMessage,
    stopStreaming,
    createNewChat,
    selectSession,
    deleteSession,
    clearCurrentChat,
    updateMessageMeta,
  };
}
