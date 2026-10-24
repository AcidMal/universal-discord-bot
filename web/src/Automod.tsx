import { FormEvent, useEffect, useState } from "react";
import { api, GuildDetail } from "./api";

const TYPES = [
  { id: "words", label: "Blocked words", help: "Punish a message that contains one of these words." },
  { id: "links", label: "Links", help: "Punish a message with a link. Leave allowed domains empty to block every link." },
  { id: "mentions", label: "Mentions", help: "Punish a message with more mentions than the limit." },
  { id: "spam", label: "Message spam", help: "Punish someone who sends too many messages in a short time." },
  { id: "raid", label: "Join raid", help: "Punish new members when too many people join in a short time." },
] as const;

const ACTIONS = [
  { id: "delete", label: "Delete message" },
  { id: "warn", label: "Warn" },
  { id: "timeout", label: "Timeout" },
  { id: "kick", label: "Kick" },
  { id: "ban", label: "Ban" },
] as const;

type Rule = {
  id: string;
  name: string;
  type: string;
  action: string;
  enabled: boolean;
  config: Record<string, unknown>;
  summary?: string;
};

type Draft = {
  name: string;
  type: string;
  action: string;
  words: string;
  domains: string;
  wholeWord: boolean;
  limit: string;
  windowSeconds: string;
  timeoutMinutes: string;
};

const EMPTY: Draft = {
  name: "",
  type: "words",
  action: "delete",
  words: "",
  domains: "",
  wholeWord: true,
  limit: "5",
  windowSeconds: "7",
  timeoutMinutes: "10",
};

function splitList(value: string) {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function draftFromRule(rule: Rule): Draft {
  const config = rule.config || {};
  const words = Array.isArray(config.words) ? config.words.map(String) : [];
  const domains = Array.isArray(config.allow_domains) ? config.allow_domains.map(String) : [];
  const timeout = Number(config.timeout_seconds || 600);
  return {
    name: rule.name,
    type: rule.type,
    action: rule.action,
    words: words.join(", "),
    domains: domains.join(", "),
    wholeWord: Boolean(config.whole_word),
    limit: String(config.max_mentions || config.max_messages || config.max_joins || 5),
    windowSeconds: String(config.window_seconds || (rule.type === "raid" ? 10 : 7)),
    timeoutMinutes: String(Math.max(1, Math.round(timeout / 60))),
  };
}

function configFromDraft(draft: Draft) {
  const timeout = Math.round(Number(draft.timeoutMinutes) * 60);
  if (draft.type === "words") {
    return { words: splitList(draft.words), whole_word: draft.wholeWord, timeout_seconds: timeout };
  }
  if (draft.type === "links") {
    return { allow_domains: splitList(draft.domains), timeout_seconds: timeout };
  }
  if (draft.type === "mentions") {
    return { max_mentions: Number(draft.limit), timeout_seconds: timeout };
  }
  if (draft.type === "spam") {
    return {
      max_messages: Number(draft.limit),
      window_seconds: Number(draft.windowSeconds),
      timeout_seconds: timeout,
    };
  }
  return {
    max_joins: Number(draft.limit),
    window_seconds: Number(draft.windowSeconds),
    timeout_seconds: timeout,
  };
}

export function AutomodPanel({
  detail,
  onError,
  onDetail,
}: {
  detail: GuildDetail;
  onError: (message: string) => void;
  onDetail: (detail: GuildDetail) => void;
}) {
  const [rows, setRows] = useState<Rule[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [channels, setChannels] = useState(detail.config.ignored_channel_ids.join(", "));
  const [roles, setRoles] = useState(detail.config.ignored_role_ids.join(", "));
  const kind = TYPES.find((item) => item.id === draft.type) || TYPES[0];
  const actions = draft.type === "raid" ? ACTIONS.filter((item) => item.id !== "delete") : ACTIONS;

  function load() {
    api
      .rules(detail.id)
      .then((next) => setRows(next as Rule[]))
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [detail.id]);

  function applyPreset(next: Partial<Draft> & Pick<Draft, "type" | "action" | "name">) {
    setEditing(null);
    setDraft({ ...EMPTY, limit: next.type === "raid" ? "8" : "5", windowSeconds: next.type === "raid" ? "10" : "7", ...next });
  }

  async function saveRule(event: FormEvent) {
    event.preventDefault();
    const body = {
      name: draft.name.trim(),
      type: draft.type,
      action: draft.action,
      enabled: true,
      config: configFromDraft(draft),
    };
    try {
      if (editing) {
        await api.patchRule(detail.id, editing, {
          name: body.name,
          action: body.action,
          config: body.config,
        });
      } else {
        await api.addRule(detail.id, body);
      }
      setDraft(EMPTY);
      setEditing(null);
      load();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  async function saveExemptions(event: FormEvent) {
    event.preventDefault();
    try {
      await api.saveConfig(detail.id, {
        ignored_channel_ids: splitList(channels),
        ignored_role_ids: splitList(roles),
      });
      onDetail(await api.guild(detail.id));
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <section className="stack">
      <form className="card stack" onSubmit={saveRule}>
        <div>
          <p className="eyebrow">New rule</p>
          <h2>{editing ? "Edit rule" : "Add a rule"}</h2>
          <p className="hint">{kind.help}</p>
        </div>
        <div className="presets">
          <button
            className="preset"
            type="button"
            onClick={() => applyPreset({ name: "Blocked words", type: "words", action: "delete" })}
          >
            Blocked words
          </button>
          <button
            className="preset"
            type="button"
            onClick={() => applyPreset({ name: "Blocked links", type: "links", action: "delete" })}
          >
            Blocked links
          </button>
          <button
            className="preset"
            type="button"
            onClick={() => applyPreset({ name: "Mention limit", type: "mentions", action: "delete", limit: "5" })}
          >
            Mention limit
          </button>
          <button
            className="preset"
            type="button"
            onClick={() =>
              applyPreset({
                name: "Message spam",
                type: "spam",
                action: "timeout",
                limit: "5",
                windowSeconds: "7",
                timeoutMinutes: "10",
              })
            }
          >
            Message spam
          </button>
          <button
            className="preset"
            type="button"
            onClick={() =>
              applyPreset({
                name: "Join raid",
                type: "raid",
                action: "kick",
                limit: "8",
                windowSeconds: "10",
              })
            }
          >
            Join raid
          </button>
        </div>
        <div className="field-grid">
          <label>
            Name
            <input
              value={draft.name}
              placeholder="Blocked words"
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </label>
          <label>
            Watches
            <select
              value={draft.type}
              onChange={(event) => {
                const type = event.target.value;
                const action = type === "raid" && draft.action === "delete" ? "kick" : draft.action;
                setDraft({
                  ...draft,
                  type,
                  action,
                  limit: type === "raid" ? "8" : draft.limit,
                  windowSeconds: type === "raid" ? "10" : type === "spam" ? "7" : draft.windowSeconds,
                });
              }}
            >
              {TYPES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            When it matches
            <select value={draft.action} onChange={(event) => setDraft({ ...draft, action: event.target.value })}>
              {actions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {draft.action === "timeout" ? (
            <label>
              Timeout minutes
              <input
                value={draft.timeoutMinutes}
                onChange={(event) => setDraft({ ...draft, timeoutMinutes: event.target.value })}
              />
            </label>
          ) : null}
        </div>
        {draft.type === "words" ? (
          <>
            <label>
              Words, separated by commas
              <textarea value={draft.words} onChange={(event) => setDraft({ ...draft, words: event.target.value })} />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.wholeWord}
                onChange={(event) => setDraft({ ...draft, wholeWord: event.target.checked })}
              />
              Match the whole word only
            </label>
          </>
        ) : null}
        {draft.type === "links" ? (
          <label>
            Allowed domains, separated by commas
            <input
              value={draft.domains}
              placeholder="youtube.com, tenor.com"
              onChange={(event) => setDraft({ ...draft, domains: event.target.value })}
            />
          </label>
        ) : null}
        {draft.type === "mentions" ? (
          <label>
            Mentions allowed in one message
            <input value={draft.limit} onChange={(event) => setDraft({ ...draft, limit: event.target.value })} />
          </label>
        ) : null}
        {draft.type === "spam" || draft.type === "raid" ? (
          <div className="field-grid">
            <label>
              {draft.type === "spam" ? "Messages allowed" : "Joins allowed"}
              <input value={draft.limit} onChange={(event) => setDraft({ ...draft, limit: event.target.value })} />
            </label>
            <label>
              Within seconds
              <input
                value={draft.windowSeconds}
                onChange={(event) => setDraft({ ...draft, windowSeconds: event.target.value })}
              />
            </label>
          </div>
        ) : null}
        <div className="inline">
          <button className="button" type="submit">
            {editing ? "Save rule" : "Add rule"}
          </button>
          {editing ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                setEditing(null);
                setDraft(EMPTY);
              }}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </form>
      {rows.length === 0 ? <p className="card">No rules yet. Start from one of the presets above.</p> : null}
      {rows.map((row) => (
        <article className="card" key={row.id}>
          <header className="split">
            <div>
              <strong>{row.name}</strong>
              <p className="hint">{row.summary || `${row.type} · ${row.action}`}</p>
            </div>
            <span className={row.enabled ? "pill online" : "pill offline"}>{row.enabled ? "on" : "off"}</span>
          </header>
          <div className="inline">
            <button
              className="ghost"
              onClick={() => {
                setEditing(row.id);
                setDraft(draftFromRule(row));
              }}
            >
              Edit
            </button>
            <button
              className="ghost"
              onClick={() =>
                api
                  .patchRule(detail.id, row.id, { enabled: !row.enabled })
                  .then(load)
                  .catch((err: Error) => onError(err.message))
              }
            >
              {row.enabled ? "Turn off" : "Turn on"}
            </button>
            <button
              className="ghost"
              onClick={() =>
                api
                  .deleteRule(detail.id, row.id)
                  .then(load)
                  .catch((err: Error) => onError(err.message))
              }
            >
              Delete
            </button>
          </div>
        </article>
      ))}
      <form className="card stack" onSubmit={saveExemptions}>
        <div>
          <p className="eyebrow">Skip</p>
          <h2>Channels and roles</h2>
          <p className="hint">
            Messages in these channels, and members with these roles, skip automod. Staff who can warn are already
            skipped.
          </p>
        </div>
        <label>
          Channel IDs, separated by commas
          <input value={channels} onChange={(event) => setChannels(event.target.value)} />
        </label>
        <label>
          Role IDs, separated by commas
          <input value={roles} onChange={(event) => setRoles(event.target.value)} />
        </label>
        <button className="button" type="submit">
          Save exemptions
        </button>
      </form>
    </section>
  );
}
