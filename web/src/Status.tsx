import { FormEvent, useEffect, useState } from "react";
import { api, BotSettings, ClusterStatus, ShardStatus } from "./api";

function Pill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{status}</span>;
}

function ShardRow({ shard }: { shard: ShardStatus }) {
  return (
    <li>
      <span>Shard {shard.shard_id}</span>
      <span className="shard-meta">
        <Pill status={shard.status} />
        <span>{shard.latency_ms === null ? "—" : `${shard.latency_ms} ms`}</span>
      </span>
    </li>
  );
}

export function HealthPanel() {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stopped = false;
    async function tick() {
      try {
        const next = await api.status();
        if (!stopped) {
          setStatus(next);
          setError("");
        }
      } catch (err) {
        if (!stopped) setError((err as Error).message);
      }
    }
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="stack">
      <div className="card">
        <p className="eyebrow">Live status</p>
        <h2>Nodes and shards</h2>
        <p>Public. Refreshes every 2 seconds from the nodes talking to this web server.</p>
        {error ? <p className="error">{error}</p> : null}
        {status ? (
          <div className="summary">
            <span>
              {status.summary.nodes_online}/{status.summary.nodes_total} nodes online
            </span>
            <span>
              {status.summary.shards_ready}/{status.summary.shards_total} shards ready
            </span>
          </div>
        ) : (
          <p>Waiting for the first reading.</p>
        )}
      </div>
      {status?.nodes.map((node) => (
        <article className="card" key={node.node_id}>
          <header className="split">
            <div>
              <strong>{node.hostname}</strong>
              <p>
                {node.role} · {node.node_id.slice(0, 8)} · seen {node.age_seconds}s ago
              </p>
            </div>
            <Pill status={node.status} />
          </header>
          {node.shards.length === 0 ? (
            <p>{node.role === "api" ? "Web server heartbeat. No shards." : "No shards claimed."}</p>
          ) : (
            <ul className="shards">
              {node.shards.map((shard) => (
                <ShardRow key={shard.shard_id} shard={shard} />
              ))}
            </ul>
          )}
        </article>
      ))}
      {status && status.unassigned_shards.length > 0 ? (
        <article className="card">
          <strong>Unassigned shards</strong>
          <ul className="shards">
            {status.unassigned_shards.map((shard) => (
              <ShardRow key={shard.shard_id} shard={shard} />
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}

export function BotSettingsPanel({ onSaved }: { onSaved: (message: string) => void }) {
  const [form, setForm] = useState<BotSettings>({
    presence: "online",
    activity_type: "custom",
    status_text: "",
  });
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .botSettings()
      .then(setForm)
      .catch((err: Error) => setError(err.message));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      const saved = await api.saveBotSettings(form);
      setForm(saved);
      onSaved("Bot status saved. Connected nodes pick it up immediately.");
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="card stack" onSubmit={save}>
      <p className="eyebrow">Bot admin</p>
      <h2>Presence</h2>
      <p>This is the status people see on the bot account. It applies to every gateway node.</p>
      {error ? <p className="error">{error}</p> : null}
      <label>
        Status
        <select
          value={form.presence}
          onChange={(event) => setForm({ ...form, presence: event.target.value })}
        >
          {["online", "idle", "dnd", "invisible"].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Activity
        <select
          value={form.activity_type}
          onChange={(event) => setForm({ ...form, activity_type: event.target.value })}
        >
          {["custom", "playing", "watching", "listening"].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
      </label>
      <label>
        Status text
        <input
          value={form.status_text}
          maxLength={128}
          placeholder="Watching the gates"
          onChange={(event) => setForm({ ...form, status_text: event.target.value })}
        />
      </label>
      <button className="button" type="submit">
        Save bot status
      </button>
    </form>
  );
}
