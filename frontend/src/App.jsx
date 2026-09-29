import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchBedrockCatalog,
  fetchConfig,
  fetchHealth,
  sendChat,
  sendChatStream,
  updateConfig,
} from "./api";
import "./App.css";

const ALLOWED_ATTACHMENT_TYPES = [
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  "application/pdf",
  "text/plain",
  "text/csv",
  "application/csv",
];
const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_ATTACHMENTS = 5;

function resolveMediaType(file) {
  if (ALLOWED_ATTACHMENT_TYPES.includes(file.type)) {
    return file.type;
  }
  if (file.name.toLowerCase().endsWith(".csv")) {
    return "text/csv";
  }
  return file.type;
}

async function fileToAttachment(file) {
  const mediaType = resolveMediaType(file);
  if (!ALLOWED_ATTACHMENT_TYPES.includes(mediaType)) {
    throw new Error(`Unsupported file type: ${file.type || file.name}`);
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    throw new Error("File too large (max 5 MB).");
  }
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      resolve(result.split(",")[1]);
    };
    reader.onerror = () => reject(new Error("Failed to read file."));
    reader.readAsDataURL(file);
  });
  return {
    filename: file.name,
    media_type: mediaType,
    data,
  };
}

export default function App() {
  const [models, setModels] = useState([]);
  const [regions, setRegions] = useState([]);
  const [config, setConfig] = useState(null);
  const [health, setHealth] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [showLocalSettings, setShowLocalSettings] = useState(false);
  const [localEndpoint, setLocalEndpoint] = useState("");
  const [localModel, setLocalModel] = useState("");
  const [localToken, setLocalToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);

  const isBedrock = config?.provider !== "local";
  const bedrockCatalogOk = !isBedrock || (regions.length > 0 && models.length > 0);
  const chatReady = (config?.chat_ready ?? health?.chat_ready) && bedrockCatalogOk;
  const bedrockError = config?.bedrock_error ?? health?.bedrock_error;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const loadBedrockCatalog = useCallback(async () => {
    const catalog = await fetchBedrockCatalog();
    setRegions(catalog.regions);
    setModels(catalog.models);
    return catalog;
  }, []);

  const loadInitialData = useCallback(async () => {
    try {
      const [configData, healthData] = await Promise.all([
        fetchConfig(),
        fetchHealth(),
      ]);
      setConfig(configData);
      setHealth(healthData);
      setLocalEndpoint(configData.local_endpoint_url || "");
      setLocalModel(configData.local_model_id || "");
      setLocalToken("");
      setError(null);

      if (configData.provider !== "local") {
        await loadBedrockCatalog();
      } else {
        setRegions([]);
        setModels([]);
      }
    } catch (err) {
      setRegions([]);
      setModels([]);
      setError(err.message || "Failed to connect to the API.");
    }
  }, [loadBedrockCatalog]);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  const applyConfig = async (updates) => {
    const updated = await updateConfig(updates);
    setConfig(updated);
    setLocalEndpoint(updated.local_endpoint_url || "");
    setLocalModel(updated.local_model_id || "");
    if (updates.clear_local_api_token) {
      setLocalToken("");
    }
    if (updated.provider !== "local") {
      await loadBedrockCatalog();
    }
    setError(null);
    return updated;
  };

  const handleProviderChange = async (provider) => {
    try {
      await applyConfig({ provider });
      if (provider === "local") {
        setRegions([]);
        setModels([]);
        setShowLocalSettings(true);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const handleModelChange = async (modelId) => {
    try {
      await applyConfig({ model_id: modelId });
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRegionChange = async (region) => {
    try {
      await applyConfig({ aws_region: region });
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSaveLocalSettings = async () => {
    try {
      const updates = {
        provider: "local",
        local_endpoint_url: localEndpoint.trim(),
        local_model_id: localModel.trim(),
      };
      if (localToken.trim()) {
        updates.local_api_token = localToken.trim();
      }
      await applyConfig(updates);
      setShowLocalSettings(false);
    } catch (err) {
      setError(err.message);
    }
  };

  const appendAssistantToken = (text) => {
    setMessages((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last?.role === "assistant") {
        updated[updated.length - 1] = {
          ...last,
          content: last.content + text,
        };
      }
      return updated;
    });
  };

  const handleAttachFiles = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;

    try {
      const remaining = MAX_ATTACHMENTS - pendingAttachments.length;
      if (remaining <= 0) {
        throw new Error(`At most ${MAX_ATTACHMENTS} attachments per message.`);
      }
      const selected = files.slice(0, remaining);
      const encoded = await Promise.all(selected.map(fileToAttachment));
      setPendingAttachments((prev) => [...prev, ...encoded]);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  };

  const removePendingAttachment = (index) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if ((!trimmed && !pendingAttachments.length) || loading) return;

    const userMessage = {
      role: "user",
      content: trimmed,
      attachments: pendingAttachments,
    };
    // Drop in-progress UI placeholders (e.g. empty streaming assistant bubbles).
    const history = messages.filter(
      (m) => m.content?.trim() || (m.attachments?.length ?? 0) > 0,
    );
    const nextMessages = [...history, userMessage];
    const chatPayload = {
      messages: nextMessages,
      model_id: isBedrock ? config?.model_id : config?.local_model_id,
      system_prompt: systemPrompt.trim() || undefined,
    };

    setMessages([...nextMessages, { role: "assistant", content: "" }]);
    setInput("");
    setPendingAttachments([]);
    setLoading(true);
    setError(null);

    let streamed = false;

    try {
      await sendChatStream(chatPayload, {
        onToken: (text) => {
          streamed = true;
          appendAssistantToken(text);
        },
      });
    } catch (streamErr) {
      if (!streamed) {
        try {
          setMessages(nextMessages);
          const response = await sendChat(chatPayload);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: response.content },
          ]);
        } catch (err) {
          setError(err.message);
          setMessages(messages);
          setInput(trimmed);
          setPendingAttachments(userMessage.attachments);
        }
      } else {
        setError(streamErr.message);
      }
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const apiReady = health?.status === "ok";

  return (
    <div className="app">
      <header className="header">
        <h1>LLM Playground</h1>
        <p>Switch between AWS Bedrock and a local OpenAI-compatible endpoint.</p>
      </header>

      <div className="status-bar">
        <span
          className={`status-dot ${apiReady ? "ok" : "error"}`}
          aria-hidden="true"
        />
        <span>
          API:{" "}
          <span className="status-label">
            {apiReady ? "Connected" : "Unavailable"}
          </span>
        </span>
        <span
          className={`status-dot ${chatReady ? "ok" : "warn"}`}
          aria-hidden="true"
        />
        <span>
          Provider:{" "}
          <span className="status-label">
            {isBedrock ? "AWS Bedrock" : "Local LLM"}
            {chatReady ? " (ready)" : " (not configured)"}
          </span>
        </span>
      </div>

      {(error || (isBedrock && bedrockError)) && (
        <div className="error-banner">{error || bedrockError}</div>
      )}

      <div className="provider-toggle">
        <button
          type="button"
          className={`provider-btn ${isBedrock ? "active" : ""}`}
          onClick={() => handleProviderChange("bedrock")}
        >
          AWS Bedrock
        </button>
        <button
          type="button"
          className={`provider-btn ${!isBedrock ? "active" : ""}`}
          onClick={() => handleProviderChange("local")}
        >
          Local LLM
        </button>
      </div>

      {isBedrock ? (
        <div className="controls">
          <div className="control-group">
            <label htmlFor="model-select">Bedrock model</label>
            <select
              id="model-select"
              value={config?.model_id ?? ""}
              onChange={(e) => handleModelChange(e.target.value)}
              disabled={!models.length}
            >
              {models.length === 0 ? (
                <option value="">No models configured</option>
              ) : (
                models.map((m) => (
                  <option key={m.model_id} value={m.model_id}>
                    {m.display_name} ({m.provider})
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="control-group">
            <label htmlFor="region-select">Region</label>
            <select
              id="region-select"
              value={config?.aws_region ?? ""}
              onChange={(e) => handleRegionChange(e.target.value)}
              disabled={!regions.length}
            >
              {regions.length === 0 ? (
                <option value="">No regions configured</option>
              ) : (
                regions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))
              )}
            </select>
          </div>
        </div>
      ) : (
        <div className="local-panel">
          <button
            type="button"
            className="system-prompt-toggle"
            onClick={() => setShowLocalSettings((v) => !v)}
          >
            {showLocalSettings ? "− Hide local endpoint settings" : "+ Local endpoint settings"}
          </button>
          {showLocalSettings && (
            <div className="local-settings">
              <div className="control-group">
                <label htmlFor="local-endpoint">Endpoint URL</label>
                <input
                  id="local-endpoint"
                  className="text-input"
                  placeholder="http://localhost:11434/v1"
                  value={localEndpoint}
                  onChange={(e) => setLocalEndpoint(e.target.value)}
                />
              </div>
              <div className="control-group">
                <label htmlFor="local-model">Model name</label>
                <input
                  id="local-model"
                  className="text-input"
                  placeholder="llama3.2"
                  value={localModel}
                  onChange={(e) => setLocalModel(e.target.value)}
                />
              </div>
              <div className="control-group">
                <label htmlFor="local-token">
                  API token {config?.local_token_configured ? "(configured)" : "(optional)"}
                </label>
                <input
                  id="local-token"
                  type="password"
                  className="text-input"
                  placeholder="Bearer token if required"
                  value={localToken}
                  onChange={(e) => setLocalToken(e.target.value)}
                  autoComplete="off"
                />
              </div>
              <button
                type="button"
                className="save-local-btn"
                onClick={handleSaveLocalSettings}
              >
                Save local settings
              </button>
              <p className="local-hint">
                Works with Ollama, vLLM, LM Studio, and other OpenAI-compatible servers.
                Token is stored on the backend only and never returned to the browser.
              </p>
            </div>
          )}
          {!showLocalSettings && config?.local_endpoint_url && (
            <p className="local-summary mono">
              {config.local_endpoint_url} → {config.local_model_id}
            </p>
          )}
        </div>
      )}

      <div className="chat-area">
        <div className="messages">
          {messages.length === 0 && !loading && (
            <div className="empty-state">
              {isBedrock
                ? "Send a message to chat with your selected Bedrock model."
                : "Configure your local endpoint, then send a message."}
              {!chatReady && (
                <>
                  <br />
                  <br />
                  {isBedrock
                    ? "Configure AWS credentials on the backend, or switch to Local LLM."
                    : "Open local endpoint settings and enter URL + model name."}
                </>
              )}
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              <span className="message-role">{msg.role}</span>
              <div className="message-bubble">
                {msg.attachments?.length > 0 && (
                  <div className="message-attachments">
                    {msg.attachments.map((att, j) => (
                      att.media_type?.startsWith("image/")
                        ? (
                          <img
                            key={j}
                            className="message-image"
                            src={`data:${att.media_type};base64,${att.data}`}
                            alt={att.filename}
                          />
                        )
                        : (
                          <span key={j} className="attachment-chip">
                            {att.filename}
                          </span>
                        )
                    ))}
                  </div>
                )}
                {msg.content ||
                  (loading && i === messages.length - 1 && msg.role === "assistant"
                    ? <span className="loading-dots">Thinking</span>
                    : "")}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <button
            type="button"
            className="system-prompt-toggle"
            onClick={() => setShowSystemPrompt((v) => !v)}
          >
            {showSystemPrompt ? "− Hide system prompt" : "+ System prompt (optional)"}
          </button>
          {showSystemPrompt && (
            <textarea
              className="system-prompt-input"
              placeholder="Set behavior instructions for the model..."
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={2}
            />
          )}
          {pendingAttachments.length > 0 && (
            <div className="pending-attachments">
              {pendingAttachments.map((att, i) => (
                <div key={i} className="pending-attachment">
                  {att.media_type.startsWith("image/") ? (
                    <img
                      className="pending-thumb"
                      src={`data:${att.media_type};base64,${att.data}`}
                      alt={att.filename}
                    />
                  ) : (
                    <span className="attachment-chip">{att.filename}</span>
                  )}
                  <button
                    type="button"
                    className="remove-attachment"
                    onClick={() => removePendingAttachment(i)}
                    aria-label={`Remove ${att.filename}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="input-row">
            <input
              ref={fileInputRef}
              type="file"
              className="file-input"
              accept={[...ALLOWED_ATTACHMENT_TYPES, ".csv"].join(",")}
              multiple
              onChange={handleAttachFiles}
            />
            <button
              type="button"
              className="attach-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading || !chatReady || pendingAttachments.length >= MAX_ATTACHMENTS}
              title="Attach image, document, or CSV"
            >
              Attach
            </button>
            <textarea
              ref={inputRef}
              className="prompt-input"
              placeholder={
                chatReady
                  ? "Type a message… (Enter to send, Shift+Enter for newline)"
                  : "Configure your provider before chatting"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading || !chatReady}
              rows={1}
            />
            <button
              type="button"
              className="send-btn"
              onClick={handleSend}
              disabled={loading || (!input.trim() && !pendingAttachments.length) || !chatReady}
            >
              {loading ? "…" : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
