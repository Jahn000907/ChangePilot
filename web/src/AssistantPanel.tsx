import { FormEvent, useEffect, useRef, useState } from "react";

import { assistantApi } from "./api";
import type {
  ConversationDetail, ConversationSummary, WorkflowSuggestion,
} from "./assistantTypes";
import { formatShanghaiTime } from "./display";
import MarkdownMessage from "./MarkdownMessage";

interface Props {
  onSuggestion: (suggestion: WorkflowSuggestion) => void;
}

export default function AssistantPanel({ onSuggestion }: Props) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [current, setCurrent] = useState<ConversationDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [suggestion, setSuggestion] = useState<WorkflowSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    void assistantApi.list().then(setConversations).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "无法加载会话");
    });
  }, []);

  async function openConversation(id: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    setSuggestion(null);
    try {
      setCurrent(await assistantApi.get(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法打开会话");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  async function createConversation() {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const created = await assistantApi.create();
      setConversations(await assistantApi.list());
      setCurrent(await assistantApi.get(created.id));
      setSuggestion(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法新建会话");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim() || !current || busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    const content = draft.trim();
    try {
      const turn = await assistantApi.send(current.id, content);
      setCurrent(await assistantApi.get(current.id));
      setConversations(await assistantApi.list());
      setSuggestion(turn.workflow_suggestion);
      setDraft("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "消息发送失败");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  return (
    <section className="panel assistant-panel">
      <div className="panel-heading">
        <div>
          <span className="section-number">AI</span>
          <h3>企业智能助手</h3>
          <p>用自然语言查询真实业务数据；正式工程变更仍需独立审批。</p>
        </div>
      </div>
      <div className="assistant-layout">
        <aside className="assistant-sidebar">
          <button type="button" className="button button-primary" onClick={createConversation} disabled={loading}>
            新建对话
          </button>
          <div className="assistant-conversations">
            {conversations.length === 0 && <p className="muted">还没有对话</p>}
            {conversations.map((item) => (
              <button key={item.id} type="button"
                className={current?.id === item.id ? "conversation active" : "conversation"}
                onClick={() => void openConversation(item.id)} disabled={loading}>
                <strong>{item.title}</strong>
                <small>{formatShanghaiTime(item.updated_at)}</small>
              </button>
            ))}
          </div>
        </aside>
        <div className="assistant-main">
          <div className="assistant-messages" aria-live="polite">
            {!current && <div className="assistant-empty">选择已有对话，或新建对话开始查询。</div>}
            {current && current.messages.length === 0 && (
              <div className="assistant-empty">试试提问：“ROB-P100 有哪些零件？”或“BRG-6204-A 库存多少？”</div>
            )}
            {current?.messages.map((message) => (
              <div key={message.id} className={`assistant-message ${message.role}`}>
                <span>{message.role === "user" ? "我" : "智能助手"}</span>
                {message.role === "assistant"
                  ? <MarkdownMessage content={message.content} />
                  : <p>{message.content}</p>}
                <time dateTime={message.created_at}>{formatShanghaiTime(message.created_at)}</time>
              </div>
            ))}
            {loading && current && <p className="assistant-loading" role="status">正在查询企业数据并整理回答，请稍候…</p>}
          </div>
          {suggestion && (
            <div className="assistant-suggestion">
              <span>如需进入受控流程，请补全事件信息后启动：</span>
              <button type="button" className="button button-secondary" onClick={() => onSuggestion(suggestion)}>
                {suggestion.label}
              </button>
            </div>
          )}
          {error && <p className="assistant-error" role="alert">{error}</p>}
          <form className="assistant-composer" onSubmit={send}>
            <textarea value={draft} onChange={(event) => setDraft(event.target.value)}
              placeholder="输入业务问题；涉及事实时，助手会使用只读工具核对…"
              rows={2} disabled={!current || loading} />
            <button type="submit" className="button button-primary"
              disabled={!current || loading || !draft.trim()}>
              {loading ? "查询中…" : "发送"}
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
