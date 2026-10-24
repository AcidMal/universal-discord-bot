import { FormEvent, useEffect, useState } from "react";
import { api, applyTokens, GuildDetail, GuildSummary, ThemePayload } from "./api";
import { AutomodPanel } from "./Automod";
import { BotSettingsPanel, HealthPanel } from "./Status";
import { TwitchPanel } from "./Twitch";

const TABS = ["Overview", "Server Settings", "Cases", "Reports", "Notes", "Tickets", "Automod", "Twitch", "Staff", "Theme"] as const;
const PRESETS = ["midnight", "light", "nord", "rose", "custom"] as const;
const PRESET_COLORS: Record<string, Pick<ThemePayload, "accent" | "background" | "surface" | "text" | "radius">> = {
  midnight: { accent: "#7C5CFF", background: "#0B0C10", surface: "#15171E", text: "#E8EAF0", radius: "8px" },
  light: { accent: "#4F46E5", background: "#F7F7F5", surface: "#FFFFFF", text: "#111318", radius: "8px" },
  nord: { accent: "#88C0D0", background: "#2E3440", surface: "#3B4252", text: "#ECEFF4", radius: "8px" },
  rose: { accent: "#E11D48", background: "#1C1418", surface: "#2A1D22", text: "#FDE8EE", radius: "8px" },
};
const MODULES = ["cases", "automod", "lockdown", "reports", "notes", "tickets"] as const;
const MODULE_LABELS: Record<(typeof MODULES)[number], string> = {
  cases: "Cases",
  automod: "Automod",
  lockdown: "Lockdown",
  reports: "Reports",
  notes: "Notes",
  tickets: "Tickets",
};

function tabSlug(tab: string) {
  if (tab === "Server Settings") return "settings";
  return tab.toLowerCase();
}

function tabPath(guildId: string, tab: string) {
  if (tab === "Overview") return `/${guildId}`;
  return `/${guildId}/${tabSlug(tab)}`;
}

function Switch({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="switch">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="switch-track" />
    </label>
  );
}

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

function Icon({ name }: { name: "status" | "bot" | "servers" | "menu" }) {
  if (name === "status") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 12h4l2.5-6 4.5 12L16.5 12H21" />
      </svg>
    );
  }
  if (name === "bot") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
      </svg>
    );
  }
  if (name === "servers") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

function readRoute(): Route {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "bot") return { view: "bot", guildId: "", tab: "Overview" };
  if (parts[0] === "servers") return { view: "servers", guildId: "", tab: "Overview" };
  if (parts[0] && /^\d{5,}$/.test(parts[0])) {
    const raw = (parts[1] || "").toLowerCase();
    const tab = TABS.find((item) => tabSlug(item) === raw || item.toLowerCase() === raw) || "Overview";
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
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onPop = () => setRoute(readRoute());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [route.view, route.guildId, route.tab]);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointer(event: MouseEvent) {
      const target = event.target;
      if (target instanceof Element && target.closest(".section-menu")) return;
      setMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

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
  }, [route.guildId, route.tab, username]);

  const showServer = Boolean(username && route.guildId);
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
  const title = showServer
    ? detail?.name || "Server"
    : route.view === "bot"
      ? "Bot settings"
      : route.view === "servers"
        ? "Servers"
        : "Live status";
  const eyebrow = showServer ? route.tab : route.view === "bot" ? "Admin" : route.view === "servers" ? "Directory" : "Public";

  return (
    <div className="shell">
      <header>
        <div className="header-title">
          {showServer ? (
            <div className="section-menu">
              <button
                className={menuOpen ? "icon-button active" : "icon-button"}
                aria-label="Server sections"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((open) => !open)}
              >
                <Icon name="menu" />
              </button>
              {menuOpen ? (
                <div className="menu-panel" role="menu">
                  {TABS.map((item) => (
                    <button
                      key={item}
                      className={item === route.tab ? "nav active" : "nav"}
                      role="menuitem"
                      onClick={() => go(tabPath(route.guildId, item))}
                    >
                      <span>{item}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <strong className="page-title">{title}</strong>
          </div>
        </div>
        <div className="header-actions">
          <button
            className={route.view === "status" ? "icon-button active" : "icon-button"}
            aria-label="Status"
            title="Status"
            onClick={() => go("/")}
          >
            <Icon name="status" />
          </button>
          {username ? (
            <button
              className={route.view === "servers" && !route.guildId ? "icon-button active" : "icon-button"}
              aria-label="Servers"
              title="Servers"
              onClick={() => go("/servers")}
            >
              <Icon name="servers" />
            </button>
          ) : null}
          {isAdmin ? (
            <button
              className={route.view === "bot" ? "icon-button active" : "icon-button"}
              aria-label="Bot admin"
              title="Bot admin"
              onClick={() => go("/bot")}
            >
              <Icon name="bot" />
            </button>
          ) : null}
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
        <main>
          {error ? <p className="error">{error}</p> : null}
          {notice ? <p className="notice">{notice}</p> : null}
          {route.view === "status" ? <HealthPanel /> : null}
          {route.view === "bot" && isAdmin ? <BotSettingsPanel onSaved={setNotice} /> : null}
          {route.view === "servers" && !route.guildId && !username ? (
            <p className="card">Sign in to see your servers.</p>
          ) : null}
          {username && route.view === "servers" && !route.guildId ? (
            <section className="stack">
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
                    <button key={guild.id} className="nav" onClick={() => go(`/${guild.id}`)}>
                      <span>{guild.name}</span>
                      <small>{guild.access}</small>
                    </button>
                  ))}
                </div>
              ))}
            </section>
          ) : null}
          {route.guildId && !username ? <p className="card">Sign in to open this server.</p> : null}
          {showServer ? (
            <>
          {detail && route.tab === "Overview" ? <Overview key={detail.id} detail={detail} /> : null}
          {detail && route.tab === "Server Settings" ? (
            <ServerSettings
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
          {detail && route.tab === "Tickets" ? <Tickets key={detail.id} guildId={detail.id} onError={setError} /> : null}
          {detail && route.tab === "Twitch" ? (
            <TwitchPanel key={detail.id} guildId={detail.id} onError={setError} />
          ) : null}
          {detail && route.tab === "Automod" ? (
            <AutomodPanel
              key={detail.id}
              detail={detail}
              onError={setError}
              onDetail={setDetail}
            />
          ) : null}
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

function Overview({ detail }: { detail: GuildDetail }) {
  const toggles = detail.config.module_toggles;
  const setup = detail.setup || {
    automod_rules: 0,
    staff_roles: 0,
    twitch_alerts: 0,
    open_reports: 0,
    open_tickets: 0,
  };
  const timeoutSeconds = detail.config.timeout_default_seconds;
  const timeoutLabel =
    timeoutSeconds % 3600 === 0
      ? `${timeoutSeconds / 3600} hours`
      : timeoutSeconds % 60 === 0
        ? `${timeoutSeconds / 60} minutes`
        : `${timeoutSeconds} seconds`;
  const services = [
    { label: "Cases", tab: "cases", on: toggles.cases !== false, detail: "Warns, timeouts, kicks, and bans" },
    {
      label: "Automod",
      tab: "automod",
      on: toggles.automod !== false,
      detail: `${setup.automod_rules} rules on`,
    },
    { label: "Lockdown", tab: "settings", on: toggles.lockdown !== false, detail: "Channel lockdown from Discord" },
    {
      label: "Reports",
      tab: "reports",
      on: toggles.reports !== false,
      detail: `${setup.open_reports} open`,
    },
    { label: "Notes", tab: "notes", on: toggles.notes !== false, detail: "Staff notes on members" },
    {
      label: "Tickets",
      tab: "tickets",
      on: toggles.tickets !== false,
      detail: detail.config.ticket_category_id
        ? `${setup.open_tickets} open · category set`
        : `${setup.open_tickets} open · no category`,
    },
    {
      label: "Twitch",
      tab: "twitch",
      on: setup.twitch_alerts > 0,
      detail: setup.twitch_alerts === 1 ? "1 channel" : `${setup.twitch_alerts} channels`,
    },
    {
      label: "Staff",
      tab: "staff",
      on: setup.staff_roles > 0,
      detail: setup.staff_roles === 1 ? "1 role" : `${setup.staff_roles} roles`,
    },
    { label: "Theme", tab: "theme", on: true, detail: `${detail.theme.preset} look` },
  ];

  return (
    <section className="stack">
      <article className="card stack">
        <div>
          <p className="eyebrow">Basics</p>
          <h2>{detail.name}</h2>
        </div>
        <div className="split">
          <span className="hint">Server ID</span>
          <strong>{detail.id}</strong>
        </div>
        <div className="split">
          <span className="hint">Timezone</span>
          <strong>{detail.config.timezone}</strong>
        </div>
        <div className="split">
          <span className="hint">Language</span>
          <strong>{detail.config.locale}</strong>
        </div>
        <div className="split">
          <span className="hint">Mod log</span>
          <strong>{detail.config.log_channel_id || "Not set"}</strong>
        </div>
        <div className="split">
          <span className="hint">Ticket category</span>
          <strong>{detail.config.ticket_category_id || "Not set"}</strong>
        </div>
        <div className="split">
          <span className="hint">Default timeout</span>
          <strong>{timeoutLabel}</strong>
        </div>
        <div className="split">
          <span className="hint">Automod skips</span>
          <strong>
            {detail.config.ignored_channel_ids.length} channels · {detail.config.ignored_role_ids.length} roles
          </strong>
        </div>
      </article>
      <div>
        <p className="eyebrow">Services</p>
        <h2>What is set up</h2>
        <div className="service-grid">
          {services.map((service) => (
            <article className="card stack" key={service.label}>
              <header className="split">
                <strong>{service.label}</strong>
                <span className={service.on ? "pill online" : "pill offline"}>{service.on ? "on" : "off"}</span>
              </header>
              <p className="hint">{service.detail}</p>
              <button className="ghost" onClick={() => go(`/${detail.id}/${service.tab}`)}>
                Open
              </button>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ServerSettings({
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
  const [ticketCategory, setTicketCategory] = useState(detail.config.ticket_category_id || "");
  const [timeout, setTimeoutSeconds] = useState(String(detail.config.timeout_default_seconds));
  const [toggles, setToggles] = useState(detail.config.module_toggles);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      await api.saveConfig(detail.id, {
        timezone,
        log_channel_id: logChannel,
        ticket_category_id: ticketCategory,
        timeout_default_seconds: Number(timeout),
        module_toggles: toggles,
      });
      onSaved();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <form className="card stack" onSubmit={save}>
      <div>
        <p className="eyebrow">Server</p>
        <h2>Server Settings</h2>
        <p className="hint">Timezone, log channel, timeout, and which services are turned on.</p>
      </div>
      <label>
        Timezone
        <input value={timezone} onChange={(event) => setTimezone(event.target.value)} />
      </label>
      <label>
        Log channel ID
        <input value={logChannel} onChange={(event) => setLogChannel(event.target.value)} />
      </label>
      <label>
        Ticket category ID
        <input
          value={ticketCategory}
          placeholder="Optional category for ticket channels"
          onChange={(event) => setTicketCategory(event.target.value)}
        />
      </label>
      <label>
        Default timeout seconds
        <input value={timeout} onChange={(event) => setTimeoutSeconds(event.target.value)} />
      </label>
      <div className="switch-list">
        {MODULES.map((name) => (
          <Switch
            key={name}
            label={MODULE_LABELS[name]}
            checked={toggles[name] !== false}
            onChange={(checked) => setToggles({ ...toggles, [name]: checked })}
          />
        ))}
      </div>
      <button className="button" type="submit">
        Save settings
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
      <Table
        rows={rows}
        columns={["case_number", "type", "target_id", "moderator_id", "reason", "created_at"]}
        onDelete={(row) => {
          api
            .deleteCase(guildId, String(row.id))
            .then(() => setRows((current) => current.filter((item) => item.id !== row.id)))
            .catch((err: Error) => onError(err.message));
        }}
      />
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
            <button
              className="ghost"
              onClick={() => {
                if (!window.confirm("Delete this report?")) return;
                api
                  .deleteReport(guildId, String(row.id))
                  .then(() => setRows((current) => current.filter((item) => item.id !== row.id)))
                  .catch((err: Error) => onError(err.message));
              }}
            >
              Delete
            </button>
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
      <Table
        rows={rows}
        columns={["created_at", "author_id", "body"]}
        onDelete={(row) => {
          api
            .deleteNote(guildId, String(row.id))
            .then(() => setRows((current) => current.filter((item) => item.id !== row.id)))
            .catch((err: Error) => onError(err.message));
        }}
      />
    </section>
  );
}

function Tickets({ guildId, onError }: { guildId: string; onError: (message: string) => void }) {
  const [rows, setRows] = useState<Record<string, string | number | null>[]>([]);
  const [filter, setFilter] = useState("open");
  const [reply, setReply] = useState<Record<string, string>>({});

  function load() {
    api
      .tickets(guildId)
      .then(setRows)
      .catch((err: Error) => onError(err.message));
  }

  useEffect(() => {
    load();
  }, [guildId]);

  const visible = rows.filter((row) => (filter === "all" ? true : row.status === filter || (filter === "open" && row.status === "claimed")));

  return (
    <section className="stack">
      <div className="inline">
        {["open", "closed", "all"].map((item) => (
          <button key={item} className={filter === item ? "tab active" : "tab"} onClick={() => setFilter(item)}>
            {item === "open" ? "Open" : item === "closed" ? "Closed" : "All"}
          </button>
        ))}
      </div>
      <p className="hint">
        Members open a ticket with /ticket open or the panel from /ticket panel. Replies here are posted in the ticket
        channel. Closing deletes that channel.
      </p>
      {visible.map((row) => (
        <article className="card stack" key={String(row.id)}>
          <header className="split">
            <strong>
              #{row.number} · {row.status}
            </strong>
            <span>{row.opener_id}</span>
          </header>
          <p>{row.subject}</p>
          {row.status !== "closed" ? (
            <>
              <div className="inline">
                <button
                  className="ghost"
                  onClick={() => api.claimTicket(guildId, String(row.id)).then(load).catch((err: Error) => onError(err.message))}
                >
                  Claim
                </button>
                <button
                  className="ghost"
                  onClick={() => api.closeTicket(guildId, String(row.id)).then(load).catch((err: Error) => onError(err.message))}
                >
                  Close
                </button>
              </div>
              <form
                className="inline"
                onSubmit={(event) => {
                  event.preventDefault();
                  const body = (reply[String(row.id)] || "").trim();
                  if (!body) return;
                  api
                    .replyTicket(guildId, String(row.id), body)
                    .then(() => setReply({ ...reply, [String(row.id)]: "" }))
                    .catch((err: Error) => onError(err.message));
                }}
              >
                <input
                  placeholder="Reply in the ticket channel"
                  value={reply[String(row.id)] || ""}
                  onChange={(event) => setReply({ ...reply, [String(row.id)]: event.target.value })}
                />
                <button className="button" type="submit">
                  Send
                </button>
              </form>
            </>
          ) : null}
        </article>
      ))}
      {visible.length === 0 ? <p className="card">No tickets.</p> : null}
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

function Table({
  rows,
  columns,
  onDelete,
}: {
  rows: Record<string, unknown>[];
  columns: string[];
  onDelete?: (row: Record<string, unknown>) => void;
}) {
  if (rows.length === 0) return <p>Nothing here yet.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
            {onDelete ? <th></th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id || index)}>
              {columns.map((column) => (
                <td key={column}>{String(row[column] ?? "")}</td>
              ))}
              {onDelete ? (
                <td>
                  <button
                    className="ghost"
                    onClick={() => {
                      if (window.confirm("Delete this record?")) onDelete(row);
                    }}
                  >
                    Delete
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
