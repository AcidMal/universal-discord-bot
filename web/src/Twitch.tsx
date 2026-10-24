import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";

type Alert = {
  id: string;
  login: string;
  channel_id: string;
  enabled: boolean;
  live: boolean;
};

export function TwitchPanel({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [configured, setConfigured] = useState(true);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [login, setLogin] = useState("");
  const [channelId, setChannelId] = useState("");
  const [note, setNote] = useState("");

  function load() {
    api
      .twitch(guildId)
      .then((payload) => {
        setConfigured(payload.configured);
        setAlerts(payload.alerts);
      })
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [guildId]);

  async function add(event: FormEvent) {
    event.preventDefault();
    setNote("");
    try {
      const saved = await api.addTwitch(guildId, login.trim(), channelId.trim());
      setLogin("");
      setNote(saved.note || `When ${saved.login} goes live, an embed is posted in that channel.`);
      load();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <section className="stack">
      <form className="card stack" onSubmit={add}>
        <div>
          <p className="eyebrow">Twitch</p>
          <h2>Live alerts</h2>
          <p className="hint">
            When a channel goes live, the bot posts an embed in the Discord channel you choose. Use a login or a
            twitch.tv link.
          </p>
        </div>
        {configured ? null : (
          <p className="error">Twitch is not configured on this bot yet, so new alerts cannot be saved.</p>
        )}
        <div className="field-grid">
          <label>
            Twitch channel
            <input
              value={login}
              placeholder="shroud"
              onChange={(event) => setLogin(event.target.value)}
            />
          </label>
          <label>
            Discord channel ID
            <input
              value={channelId}
              placeholder="Channel that receives the embed"
              onChange={(event) => setChannelId(event.target.value)}
            />
          </label>
        </div>
        <button className="button" type="submit" disabled={!configured}>
          Add alert
        </button>
        {note ? <p className="notice">{note}</p> : null}
      </form>
      {alerts.length === 0 ? <p className="card">No Twitch channels yet.</p> : null}
      {alerts.map((alert) => (
        <article className="card" key={alert.id}>
          <header className="split">
            <div>
              <strong>{alert.login}</strong>
              <p className="hint">Posts in channel {alert.channel_id}</p>
            </div>
            <span className={alert.live ? "pill online" : "pill offline"}>{alert.live ? "live" : "offline"}</span>
          </header>
          <div className="inline">
            <a className="ghost" href={`https://twitch.tv/${alert.login}`} target="_blank" rel="noreferrer">
              Open channel
            </a>
            <button
              className="ghost"
              onClick={() =>
                api
                  .deleteTwitch(guildId, alert.id)
                  .then(load)
                  .catch((err: Error) => onError(err.message))
              }
            >
              Remove
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}
