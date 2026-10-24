export type GuildSummary = {
  id: string;
  name: string;
  access: string;
};

export type ThemePayload = {
  preset: string;
  accent: string;
  background: string;
  surface: string;
  text: string;
  radius: string;
  footer: string;
  author_name: string;
  logo_url: string | null;
  embed_templates: Record<string, { title: string; description: string }>;
  tokens: Record<string, string>;
  preview: { title?: string; description?: string; color?: number };
};

export type GuildDetail = {
  id: string;
  name: string;
  config: {
    locale: string;
    timezone: string;
    log_channel_id: string | null;
    ticket_category_id: string | null;
    timeout_default_seconds: number;
    module_toggles: Record<string, boolean>;
    ignored_channel_ids: string[];
    ignored_role_ids: string[];
  };
  theme: ThemePayload;
  setup?: {
    automod_rules: number;
    staff_roles: number;
    twitch_alerts: number;
    open_reports: number;
    open_tickets: number;
  };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      const plain = text.replace(/\s+/g, " ").trim();
      if (plain.startsWith("<!") || plain.startsWith("<html") || plain.includes("cf-error-details")) {
        throw new Error("Cloudflare returned an error page instead of the server list.");
      }
      throw new Error(plain.slice(0, 200) || response.statusText || "Request failed");
    }
  }
  if (response.status === 401) {
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : response.statusText;
    throw new Error(detail || "Request failed");
  }
  return body as T;
}

export type ShardStatus = {
  shard_id: number;
  status: string;
  latency_ms: number | null;
  lease_valid: boolean;
};

export type NodeStatus = {
  node_id: string;
  hostname: string;
  role: string;
  label?: string;
  status: string;
  age_seconds: number;
  shards: ShardStatus[];
};

export type ClusterStatus = {
  summary: {
    nodes_online: number;
    nodes_total: number;
    shards_ready: number;
    shards_total: number;
  };
  database?: {
    status: string;
    latency_ms: number | null;
  };
  nodes: NodeStatus[];
  unassigned_shards: ShardStatus[];
};

export type BotSettings = {
  presence: string;
  activity_type: string;
  status_text: string;
};

export const api = {
  me: () => request<{ id: string; username: string; is_admin: boolean }>("/api/me"),
  status: () => request<ClusterStatus>("/api/status"),
  botSettings: () => request<BotSettings>("/api/admin/bot"),
  saveBotSettings: (body: BotSettings) =>
    request<BotSettings>("/api/admin/bot", { method: "PUT", body: JSON.stringify(body) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  guilds: () => request<GuildSummary[]>("/api/guilds"),
  guild: (id: string) => request<GuildDetail>(`/api/guilds/${id}`),
  saveConfig: (id: string, body: unknown) =>
    request(`/api/guilds/${id}/config`, { method: "PATCH", body: JSON.stringify(body) }),
  saveTheme: (id: string, body: unknown) =>
    request<ThemePayload>(`/api/guilds/${id}/theme`, { method: "PUT", body: JSON.stringify(body) }),
  cases: (id: string, q?: string) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    const suffix = params.toString() ? `?${params}` : "";
    return request<Record<string, unknown>[]>(`/api/guilds/${id}/cases${suffix}`);
  },
  reports: (id: string) => request<Record<string, string | null>[]>(`/api/guilds/${id}/reports`),
  patchReport: (id: string, reportId: string, status: string) =>
    request(`/api/guilds/${id}/reports/${reportId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  notes: (id: string, targetId: string) =>
    request<Record<string, string>[]>(`/api/guilds/${id}/notes?target_id=${targetId}`),
  addNote: (id: string, targetId: string, body: string) =>
    request(`/api/guilds/${id}/notes`, {
      method: "POST",
      body: JSON.stringify({ target_id: targetId, body }),
    }),
  deleteNote: (id: string, noteId: string) =>
    request<void>(`/api/guilds/${id}/notes/${noteId}`, { method: "DELETE" }),
  deleteCase: (id: string, caseId: string) =>
    request<void>(`/api/guilds/${id}/cases/${caseId}`, { method: "DELETE" }),
  deleteReport: (id: string, reportId: string) =>
    request<void>(`/api/guilds/${id}/reports/${reportId}`, { method: "DELETE" }),
  tickets: (id: string) => request<Record<string, string | number | null>[]>(`/api/guilds/${id}/tickets`),
  claimTicket: (id: string, ticketId: string) =>
    request(`/api/guilds/${id}/tickets/${ticketId}/claim`, { method: "POST" }),
  closeTicket: (id: string, ticketId: string) =>
    request(`/api/guilds/${id}/tickets/${ticketId}/close`, { method: "POST" }),
  replyTicket: (id: string, ticketId: string, body: string) =>
    request<void>(`/api/guilds/${id}/tickets/${ticketId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  rules: (id: string) => request<Record<string, unknown>[]>(`/api/guilds/${id}/automod`),
  addRule: (id: string, body: unknown) =>
    request(`/api/guilds/${id}/automod`, { method: "POST", body: JSON.stringify(body) }),
  patchRule: (id: string, ruleId: string, body: unknown) =>
    request(`/api/guilds/${id}/automod/${ruleId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteRule: (id: string, ruleId: string) =>
    request<void>(`/api/guilds/${id}/automod/${ruleId}`, { method: "DELETE" }),
  twitch: (id: string) =>
    request<{
      configured: boolean;
      alerts: { id: string; login: string; channel_id: string; enabled: boolean; live: boolean }[];
    }>(`/api/guilds/${id}/twitch`),
  addTwitch: (id: string, login: string, channelId: string) =>
    request<{ login: string; note: string | null }>(`/api/guilds/${id}/twitch`, {
      method: "POST",
      body: JSON.stringify({ login, discord_channel_id: channelId }),
    }),
  deleteTwitch: (id: string, alertId: string) =>
    request<void>(`/api/guilds/${id}/twitch/${alertId}`, { method: "DELETE" }),
  staff: (id: string) => request<Record<string, unknown>[]>(`/api/guilds/${id}/staff`),
  addStaff: (id: string, body: unknown) =>
    request(`/api/guilds/${id}/staff`, { method: "POST", body: JSON.stringify(body) }),
  deleteStaff: (id: string, staffId: string) =>
    request<void>(`/api/guilds/${id}/staff/${staffId}`, { method: "DELETE" }),
};

export function applyTokens(tokens: Record<string, string>) {
  for (const [key, value] of Object.entries(tokens)) {
    document.documentElement.style.setProperty(key, value);
  }
}
