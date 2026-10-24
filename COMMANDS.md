# Slash commands

Every command is a Discord slash command. The bot does not use a text prefix. Commands are hidden from people who fail the permission check with an ephemeral reply, and they are still registered for the whole server so a configured staff role can use them without the matching Discord permission.

Durations accept `30s`, `10m`, `2h`, and `1d`. A bare number is minutes. The maximum is 28 days.

Full setup and deploy steps are in [README.md](README.md).

## Who can run what

Discord administrators can run every command. Everyone else needs the native permission in the table, or a staff role from `/setup` or the dashboard.

| Action | Native Discord permission | Staff role flag |
| --- | --- | --- |
| `/setup`, `/theme`, `/automod` | Manage Server | — |
| `/warn`, `/notes`, `/reports` staff actions | Moderate Members or Manage Server | Warn |
| `/timeout` | Moderate Members | Timeout |
| `/kick` | Kick Members | Kick |
| `/ban`, `/unban` | Ban Members | Ban |
| `/lockdown` | Manage Channels or Manage Server | Ban |
| `/report` | Any member | — |
| `/ping` | Any member | — |

The bot also refuses a punishment when the target is above the moderator or above the bot's highest role.

Modules can be turned off in the dashboard. A disabled module rejects its commands.

## Ping

### `/ping`

Any member can run this. It checks the shared database, then lists every cluster node and the shards that node holds.

| Line | Meaning |
| --- | --- |
| Database | Round trip from this bot process to Postgres |
| Node | Role (`gateway` or `api`), whether its heartbeat is online, and how long ago it was seen |
| Shard | Gateway state and websocket latency. A shard this process holds is measured live |

A node is online when its heartbeat is under 20 seconds old, stale under 60 seconds, and offline after that.

## Setup

### `/setup`

First-run wizard.

| Option | Required | Meaning |
| --- | --- | --- |
| `log_channel` | yes | Channel that receives case, report, lockdown, and automod embeds |
| `staff_role` | yes | Role allowed to warn, timeout, kick, and ban |
| `timezone` | no | IANA name such as `Australia/Sydney`. Defaults to `UTC` |

Example: `/setup log_channel:#mod-log staff_role:@Staff timezone:Australia/Sydney`

## Cases

Punishments open a numbered case, post one embed in the log channel, and edit that embed if a timed action is reversed. Case numbers are per server and come from Postgres, so two nodes cannot issue the same number.

### `/warn`

Warn a member. This does not change their Discord permissions.

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member to warn |
| `reason` | yes | Stored on the case and in the log embed |
| `evidence` | no | URL included in the log |

Example: `/warn member:@ada reason:Repeated spam evidence:https://example.com/shot.png`

### `/timeout`

Timeout a member. If `duration` is omitted, the server default is used (10 minutes until you change it).

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member to timeout |
| `reason` | yes | Why |
| `duration` | no | How long. Example: `2h` |
| `evidence` | no | Evidence URL |

When the duration ends, whichever node owns the scheduler removes the timeout and marks the case reversed.

Example: `/timeout member:@ada reason:Cool down duration:30m`

### `/kick`

Remove the member from the server. They can rejoin with a new invite.

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member to kick |
| `reason` | yes | Why |
| `evidence` | no | Evidence URL |

### `/ban`

Ban a member. Leave `duration` empty for a permanent ban.

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member to ban |
| `reason` | yes | Why |
| `duration` | no | Timed ban, such as `7d` |
| `evidence` | no | Evidence URL |

A timed ban is lifted by the scheduler. A permanent ban stays until `/unban`.

### `/unban`

| Option | Required | Meaning |
| --- | --- | --- |
| `user` | yes | User to unban. They do not have to be in the server |
| `reason` | yes | Why |

### `/case view`

Show one case to the staff member who ran the command.

| Option | Required | Meaning |
| --- | --- | --- |
| `number` | yes | Case number, without the `#` |

Example: `/case view number:12`

### `/case search`

List the 10 newest cases for a user.

| Option | Required | Meaning |
| --- | --- | --- |
| `user` | yes | User to look up |

## Notes

Notes are staff-only and are not punishments. They do not appear in the public mod log.

### `/notes add`

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member the note is about |
| `text` | yes | Note body, up to 2000 characters |

### `/notes list`

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member to look up |

The dashboard Notes tab can add and read the same records.

## Reports

### `/report`

Any member can file a report. Staff get an embed in the log channel when one is configured.

| Option | Required | Meaning |
| --- | --- | --- |
| `member` | yes | Member being reported |
| `reason` | yes | What happened |
| `message_link` | no | A Discord jump link from this server |

Example: `/report member:@ada reason:Scam link in #general message_link:https://discord.com/channels/...`

### `/reports list`

Shows open and claimed reports. Each line starts with the first characters of the report id.

### `/reports claim`

| Option | Required | Meaning |
| --- | --- | --- |
| `report_id` | yes | Full id or a unique prefix from `/reports list` |

### `/reports resolve`

Marks the report resolved.

| Option | Required | Meaning |
| --- | --- | --- |
| `report_id` | yes | Full id or a unique prefix |

### `/reports reject`

Marks the report rejected. Same option as resolve.

The dashboard Reports tab can claim, resolve, and reject the same queue.

## Lockdown

Lockdown denies `@everyone` Send Messages. The previous overwrite for each channel is stored in Postgres and put back on unlock. A timed lockdown is restored by the scheduler even if another node is handling the job.

### `/lockdown on`

| Option | Required | Meaning |
| --- | --- | --- |
| `reason` | yes | Why, written to the case |
| `channel` | no | One text channel. Empty locks every text channel the bot can edit, up to 100 |
| `duration` | no | Automatic unlock, such as `30m` |

Example: `/lockdown on reason:Raid channel:#general duration:20m`

### `/lockdown off`

Restores the saved overwrites. There are no options.

## Automod

`/automod` lists and toggles rules. Create and edit the rule body in the dashboard. Enabled rules are cached on each gateway node and dropped when Postgres sends `guild_invalidate`.

Spam and raid counts live in `automod_windows`, so two nodes agree on the same burst.

| Type | What it watches | Config |
| --- | --- | --- |
| `words` | Message text | `words` list, optional `whole_word` |
| `links` | URLs and `discord.gg` invites | `allow_domains` |
| `mentions` | User, role, and everyone mentions | `max_mentions` |
| `spam` | Messages per user | `max_messages`, `window_seconds` |
| `raid` | Joins | `max_joins`, `window_seconds` |

Actions are `delete`, `warn`, `timeout`, `kick`, and `ban`. Timeout uses `timeout_seconds` in the rule config, or 10 minutes. Message rules delete the message. Warn, timeout, kick, and ban also open a case attributed to Automod.

Staff with warn access, Manage Messages, or Administrator are not filtered. Channels and roles in the ignored lists are skipped.

### `/automod list`

Prints each rule id prefix, on/off, type, action, and name.

### `/automod toggle`

| Option | Required | Meaning |
| --- | --- | --- |
| `rule_id` | yes | Full id, a unique prefix, or the exact rule name |

## Theme

The same theme row drives Discord embeds and the dashboard. Templates are title and description only. Allowed placeholders: `{case}`, `{type}`, `{target}`, `{reason}`, `{moderator}`.

Presets: Midnight, Light, Nord, Rose. Custom colors, footer, author, and logo are edited in the dashboard. The Theme tab previews the case embed before you save.

### `/theme preview`

Sends the current case embed to you only. Nothing is saved.

### `/theme preset`

| Option | Required | Meaning |
| --- | --- | --- |
| `preset` | yes | Midnight, Light, Nord, or Rose |

Example: `/theme preset preset:Nord`

## Twitch

Manage Server is required. Alerts are per server. The same Twitch channel can post into different Discord channels in different servers.

When `PUBLIC_URL` is a public https address, Twitch pushes the alert as soon as the stream starts. Otherwise the bot checks every 10 seconds. The embed uses the server's accent color.

| Part | Content |
| --- | --- |
| Title | Stream title, linking to the stream |
| Channel | Twitch display name, also linking to the stream |
| Image | Live thumbnail |

### `/twitch add`

| Option | Required | Meaning |
| --- | --- | --- |
| `channel` | yes | Discord channel that receives the embed |
| `user` | yes | Twitch login, `@login`, or a `twitch.tv` link |

Example: `/twitch add channel:#streams user:shroud`

Running it again for the same Twitch login moves the alert to the new Discord channel.

### `/twitch remove`

| Option | Required | Meaning |
| --- | --- | --- |
| `user` | yes | Twitch login to stop watching |

### `/twitch list`

Lists each Twitch login and the Discord channel it posts to.
