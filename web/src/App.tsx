import { FormEvent, useEffect, useState } from "react";
import { api, applyTokens, GuildDetail, GuildSummary, ThemePayload } from "./api";
import { BotSettingsPanel, HealthPanel } from "./Status";

const TABS = ["Overview", "Cases", "Reports", "Notes", "Automod", "Staff", "Theme"] as const;
const PRESETS = ["midnight", "light", "nord", "rose", "custom"] as const;
const PRESET_COLORS: Record<string, Pick<ThemePayload, "accent" | "background" | "surface" | "text" | "radius">> = {
  midnight: { accent: "#7C5CFF", background: "#0B0C10", surface: "#15171E", text: "#E8EAF0", radius: "8px" },
  light: { accent: "#4F46E5", background: "#F7F7F5", surface: "#FFFFFF", text: "#111318", radius: "8px" },
  nord: { accent: "#88C0D0", background: "#2E3440", surface: "#3B4252", text: "#ECEFF4", radius: "8px" },
  rose: { accent: "#E11D48", background: "#1C1418", surface: "#2A1D22", text: "#FDE8EE", radius: "8px" },
};
const MODULES = ["cases", "automod", "lockdown", "reports", "notes"] as const;

function EmbedPreview({ theme }: { theme: ThemePayload }) {
  return (
    <article className="embed">
      <div className="embed-bar" style={{ background: theme.accent }} />
      <div>
        {theme.author_name ? <p className="embed-author">{theme.author_name}</p> : null}
        <h3>{theme.preview.title || "Case #42"}</h3>
        <p>{theme.preview.description || "Preview case. Nothing was saved."}</p>
        {theme.footer ? <p className="embed-footer">{theme.footer}</p> : null}
      </div>
    </article>
  );
}

type Tab = (typeof TABS)[number];
type Route = { view: "status" | "servers" | "bot"; guildId: string; tab: Tab };

function readRoute(): Route {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "bot") return { view: "bot", guildId: "", tab: "Overview" };
  if (parts[0] && /^\d{5,}$/.test(parts[0])) {
    const tab = TABS.find((item) => item.toLowerCase() === (parts[1] || "").toLowerCase()) || "Overview";
    return { view: "servers", guildId: parts[0], tab };
  }
  return { view: "status", guildId: "", tab: "Overview" };
}

function go(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export default function App() {
  const [username, setUsername] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [route, setRoute] = useState<Route>(readRoute);
  const [guilds, setGuilds] = useState<GuildSummary[]>([]);
  const [serverQuery, setServerQuery] = useState("");
  const [detail, setDetail] = useState<GuildDetail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const onPop = () => setRoute(readRoute());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    api
      .me()
      .then(async (user) => {
        setUsername(user.username);
        setIsAdmin(user.is_admin);
        setGuilds(await api.guilds());
      })
      .catch((err: Error) => {
        if (err.message !== "unauthorized") setError(err.message);
      });
  }, []);

  useEffect(() => {
    if (!route.guildId || !username) {
      setDetail(null);
      return;
    }
    setError("");
    api
      .guild(route.guildId)
      .then((row) => {
        setDetail(row);
        applyTokens(row.theme.tokens);
      })
      .catch((err: Error) => setError(err.message));
  }, [route.guildId, username]);

  const showServers = Boolean(username && route.view === "servers" && route.guildId);
  const query = serverQuery.trim().toLowerCase();
  const visibleGuilds = guilds.filter(
    (guild) => !query || guild.name.toLowerCase().includes(query) || guild.id.includes(query),
  );
  const groups = [
    { label: "Managers", access: "manager" },
    { label: "Staff", access: "staff" },
  ]
    .map((group) => ({ ...group, guilds: visibleGuilds.filter((guild) => guild.access === group.access) }))
    .filter((group) => group.guilds.length > 0);
  const title =
    route.view === "status" ? "Live status" : route.view === "bot" ? "Bot settings" : detail?.name || "Server";

  return (
    <div className="shell">
      <header>
        <div>
          <p className="eyebrow">Moderation</p>
          <strong className="page-title">{title}</strong>
        </div>
        <div className="header-actions">
          {username ? (
            <>
              <span className="who">{username}</span>
              <button className="ghost" onClick={() => api.logout().then(() => window.location.assign("/"))}>
                Sign out
              </button>
            </>
          ) : (
            <a className="button" href="/auth/login">
              Sign in
            </a>
          )}
        </div>
      </header>
      <div className="layout">
        <aside>
          <button className={route.view === "status" ? "nav active" : "nav"} onClick={() => go("/")}>
            <span>Status</span>
            <small>public</small>
          </button>
          {isAdmin ? (
            <button className={route.view === "bot" ? "nav active" : "nav"} onClick={() => go("/bot")}>
              <span>Bot</span>
              <small>admin</small>
            </button>
          ) : null}
          {username ? (
            <>
              <input
                className="search"
                placeholder="Search servers"
                value={serverQuery}
                onChange={(event) => setServerQuery(event.target.value)}
              />
              {guilds.length === 0 ? <p className="hint">No servers yet. Invite the bot, then refresh.</p> : null}
              {guilds.length > 0 && groups.length === 0 ? <p className="hint">No servers match.</p> : null}
              {groups.map((group) => (
                <div className="group" key={group.access}>
                  <p className="group-label">{group.label}</p>
                  {group.guilds.map((guild) => (
                    <button
                      key={guild.id}
                      className={showServers && guild.id === route.guildId ? "nav active" : "nav"}
                      onClick={() => go(`/${guild.id}`)}
                    >
                      <span>{guild.name}</span>
                      <small>{guild.access}</small>
                    </button>
                  ))}
                </div>
              ))}
            </>
          ) : (
            <p className="hint">Sign in with Discord to edit server settings.</p>
          )}
        </aside>
        <main>
          {error ? <p className="error">{error}</p> : null}
          {notice ? <p className="notice">{notice}</p> : null}
          {route.view === "status" ? <HealthPanel /> : null}
          {route.view === "bot" && isAdmin ? <BotSettingsPanel onSaved={setNotice} /> : null}
          {route.view === "servers" && !username ? (
            <p className="card">Sign in to open this server.</p>
          ) : null}
          {showServers ? (
            <>
          <nav className="tabs">
            {TABS.map((item) => (
              <button
                key={item}
                className={item === route.tab ? "tab active" : "tab"}
                onClick={() => go(item === "Overview" ? `/${route.guildId}` : `/${route.guildId}/${item.toLowerCase()}`)}
              >
                {item}
              </button>
            ))}
          </nav>
          {detail && route.tab === "Overview" ? (
            <Overview
              key={detail.id}
              detail={detail}
              onSaved={() => {
                setNotice("Server settings saved.");
                api.guild(detail.id).then(setDetail);
              }}
              onError={setError}
            />
          ) : null}
          {detail && route.tab === "Cases" ? <Cases key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Reports" ? <Reports key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Notes" ? <Notes key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Automod" ? <Automod key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Staff" ? <Staff key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Theme" ? (
            <ThemeEditor
              key={detail.id}
              detail={detail}
              onTheme={(theme) => {
                setDetail({ ...detail, theme });
                applyTokens(theme.tokens);
                setNotice("Look saved.");
              }}
              onError={setError}
            />
          ) : null}
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

function Overview({
  detail,
  onSaved,
  onError,
}: {
  detail: GuildDetail;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [timezone, setTimezone] = useState(detail.config.timezone);
  const [logChannel, setLogChannel] = useState(detail.config.log_channel_id || "");
  const [timeout, setTimeoutSeconds] = useState(String(detail.config.timeout_default_seconds));
  const [toggles, setToggles] = useState(detail.config.module_toggles);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      await api.saveConfig(detail.id, {
        timezone,
        log_channel_id: logChannel,
        timeout_default_seconds: Number(timeout),
        module_toggles: toggles,
      });
      onSaved();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <form className="card" onSubmit={save}>
      <label>
        Timezone
        <input value={timezone} onChange={(event) => setTimezone(event.target.value)} />
      </label>
      <label>
        Log channel ID
        <input value={logChannel} onChange={(event) => setLogChannel(event.target.value)} />
      </label>
      <label>
        Default timeout seconds
        <input value={timeout} onChange={(event) => setTimeoutSeconds(event.target.value)} />
      </label>
      <div className="checks">
        {MODULES.map((name) => (
          <label key={name}>
            <input
              type="checkbox"
              checked={toggles[name] !== false}
              onChange={(event) => setToggles({ ...toggles, [name]: event.target.checked })}
            />
            {name}
          </label>
        ))}
      </div>
      <button className="button" type="submit">
        Save overview
      </button>
    </form>
  );
}

function Cases({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const handle = window.setTimeout(() => {
      api
        .cases(guildId, query.trim())
        .then(setRows)
        .catch((err: Error) => onError(err.message));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [guildId, query, onError]);

  return (
    <section className="card">
      <input
        className="search"
        placeholder="Search case number, type, user, moderator, or reason"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <p className="hint">{rows.length} shown</p>
      <Table rows={rows} columns={["case_number", "type", "target_id", "moderator_id", "reason", "created_at"]} />
    </section>
  );
}

function Reports({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, string | null>[]>([]);
  const [query, setQuery] = useState("");

  function load() {
    api
      .reports(guildId)
      .then(setRows)
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [guildId]);

  const needle = query.trim().toLowerCase();
  const visible = rows.filter((row) => {
    if (!needle) return true;
    return [row.status, row.target_id, row.reason, row.reporter_id].some((value) =>
      String(value || "").toLowerCase().includes(needle),
    );
  });

  return (
    <section className="stack">
      <input
        className="search"
        placeholder="Search reports"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {visible.map((row) => (
        <article className="card" key={String(row.id)}>
          <header className="split">
            <strong>
              {row.status} · {row.target_id}
            </strong>
            <span>{row.reason}</span>
          </header>
          <div className="inline">
            {["claimed", "resolved", "rejected"].map((status) => (
              <button
                key={status}
                className="ghost"
                onClick={() =>
                  api
                    .patchReport(guildId, String(row.id), status)
                    .then(load)
                    .catch((err: Error) => onError(err.message))
                }
              >
                {status}
              </button>
            ))}
            {row.jump_url ? (
              <a href={row.jump_url} target="_blank" rel="noreferrer">
                Message
              </a>
            ) : null}
          </div>
        </article>
      ))}
      {visible.length === 0 ? <p className="card">No reports.</p> : null}
    </section>
  );
}

function Notes({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [target, setTarget] = useState("");
  const [body, setBody] = useState("");
  const [rows, setRows] = useState<Record<string, string>[]>([]);

  return (
    <section className="card">
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          api
            .addNote(guildId, target.trim(), body)
            .then(() => api.notes(guildId, target.trim()))
            .then((items) => {
              setRows(items);
              setBody("");
            })
            .catch((err: Error) => onError(err.message));
        }}
      >
        <input placeholder="User ID" value={target} onChange={(event) => setTarget(event.target.value)} />
        <textarea placeholder="Staff note" value={body} onChange={(event) => setBody(event.target.value)} />
        <button className="button" type="submit">
          Add note
        </button>
      </form>
      <Table rows={rows} columns={["created_at", "author_id", "body"]} />
    </section>
  );
}

function Automod({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState("words");
  const [action, setAction] = useState("delete");
  const [words, setWords] = useState("");
  const [limit, setLimit] = useState("5");
  const [windowSeconds, setWindowSeconds] = useState("7");

  function load() {
    api
      .rules(guildId)
      .then(setRows)
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [guildId]);

  function config() {
    if (type === "words") return { words: words.split(",").map((item) => item.trim()).filter(Boolean) };
    if (type === "links") return { allow_domains: words.split(",").map((item) => item.trim()).filter(Boolean) };
    if (type === "mentions") return { max_mentions: Number(limit) };
    if (type === "spam") return { max_messages: Number(limit), window_seconds: Number(windowSeconds) };
    return { max_joins: Number(limit), window_seconds: Number(windowSeconds) };
  }

  return (
    <section className="stack">
      <form
        className="card stack"
        onSubmit={(event) => {
          event.preventDefault();
          api
            .addRule(guildId, { name, type, action, enabled: true, config: config() })
            .then(load)
            .catch((err: Error) => onError(err.message));
        }}
      >
        <div className="inline">
          <input placeholder="Rule name" value={name} onChange={(event) => setName(event.target.value)} />
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {["words", "links", "mentions", "spam", "raid"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            {["delete", "warn", "timeout", "kick", "ban"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </div>
        <input
          placeholder={type === "links" ? "Allowed domains, comma separated" : "Words, comma separated"}
          value={words}
          onChange={(event) => setWords(event.target.value)}
        />
        <div className="inline">
          <input value={limit} onChange={(event) => setLimit(event.target.value)} />
          <input value={windowSeconds} onChange={(event) => setWindowSeconds(event.target.value)} />
        </div>
        <button className="button" type="submit">
          Add rule
        </button>
      </form>
      {rows.map((row) => (
        <article className="card split" key={String(row.id)}>
          <div>
            <strong>{String(row.name)}</strong>
            <p>
              {String(row.type)} / {String(row.action)} / {row.enabled ? "on" : "off"}
            </p>
          </div>
          <div className="inline">
            <button
              className="ghost"
              onClick={() =>
                api
                  .patchRule(guildId, String(row.id), { enabled: !row.enabled })
                  .then(load)
                  .catch((err: Error) => onError(err.message))
              }
            >
              Toggle
            </button>
            <button
              className="ghost"
              onClick={() =>
                api
                  .deleteRule(guildId, String(row.id))
                  .then(load)
                  .catch((err: Error) => onError(err.message))
              }
            >
              Delete
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}

function Staff({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [roleId, setRoleId] = useState("");

  function load() {
    api
      .staff(guildId)
      .then(setRows)
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [guildId]);

  return (
    <section className="card stack">
      <form
        className="inline"
        onSubmit={(event) => {
          event.preventDefault();
          api
            .addStaff(guildId, { role_id: roleId.trim() })
            .then(() => {
              setRoleId("");
              load();
            })
            .catch((err: Error) => onError(err.message));
        }}
      >
        <input placeholder="Role ID" value={roleId} onChange={(event) => setRoleId(event.target.value)} />
        <button className="button" type="submit">
          Add staff role
        </button>
      </form>
      {rows.map((row) => (
        <div className="split" key={String(row.id)}>
          <span>{String(row.role_id)}</span>
          <button
            className="ghost"
            onClick={() =>
              api
                .deleteStaff(guildId, String(row.id))
                .then(load)
                .catch((err: Error) => onError(err.message))
            }
          >
            Remove
          </button>
        </div>
      ))}
    </section>
  );
}

function ThemeEditor({
  detail,
  onTheme,
  onError,
}: {
  detail: GuildDetail;
  onTheme: (theme: ThemePayload) => void;
  onError: (message: string) => void;
}) {
  const [theme, setTheme] = useState(detail.theme);

  useEffect(() => {
    setTheme(detail.theme);
  }, [detail.id]);

  function update(patch: Partial<ThemePayload>) {
    const next = { ...theme, ...patch, preset: patch.preset || "custom" };
    setTheme(next);
    applyTokens({
      "--accent": next.accent,
      "--bg": next.background,
      "--surface": next.surface,
      "--text": next.text,
      "--radius": next.radius,
    });
  }

  return (
    <section className="theme-grid">
      <form
        className="card stack"
        onSubmit={(event) => {
          event.preventDefault();
          api
            .saveTheme(detail.id, theme)
            .then(onTheme)
            .catch((err: Error) => onError(err.message));
        }}
      >
        <div className="inline">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={theme.preset === preset ? "tab active" : "tab"}
              onClick={() => update({ preset, ...(PRESET_COLORS[preset] || {}) })}
            >
              {preset}
            </button>
          ))}
        </div>
        {(["accent", "background", "surface", "text"] as const).map((field) => (
          <label key={field}>
            {field}
            <input value={theme[field]} onChange={(event) => update({ [field]: event.target.value })} />
          </label>
        ))}
        <label>
          Radius
          <input value={theme.radius} onChange={(event) => update({ radius: event.target.value })} />
        </label>
        <label>
          Footer
          <input value={theme.footer} onChange={(event) => update({ footer: event.target.value })} />
        </label>
        <label>
          Author
          <input
            value={theme.author_name}
            onChange={(event) => update({ author_name: event.target.value })}
          />
        </label>
        <label>
          Logo URL
          <input
            value={theme.logo_url || ""}
            onChange={(event) => update({ logo_url: event.target.value })}
          />
        </label>
        <button className="button" type="submit">
          Save look
        </button>
      </form>
      <div className="card">
        <p className="eyebrow">Live preview</p>
        <EmbedPreview theme={theme} />
      </div>
    </section>
  );
}

function Table({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  if (rows.length === 0) return <p>Nothing here yet.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id || index)}>
              {columns.map((column) => (
                <td key={column}>{String(row[column] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
