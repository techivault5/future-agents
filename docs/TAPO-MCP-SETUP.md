# Tapo MCP — camera setup

Runs [mihai-dinculescu/tapo `tapo-mcp`](https://github.com/mihai-dinculescu/tapo/tree/main/tapo-mcp)
so Claude can list Tapo devices, read state, control plugs/bulbs, and **take camera snapshots**.

## Supported cameras

C210, C220, C225, C325WB, C520WS, TC40, TC70 (others may work but are untested upstream).

## 1 · Prepare the camera

| Step | Where |
|---|---|
| Camera on same LAN as the host running the server | router |
| Create a **Camera Account** (username + password) | Tapo app → camera → ⚙ Settings → Advanced Settings → Camera Account |
| Note your LAN broadcast address | e.g. host IP `192.168.1.x/24` → `192.168.1.255` |

The camera account is separate from your TP-Link cloud login. `take_snapshot` needs it.

## 2 · Configure

```bash
cp .env.example .env            # .env is gitignored
openssl rand -hex 32            # paste as TAPO_MCP_API_KEY
$EDITOR .env                    # fill every TAPO_MCP_* value
```

| Var | Value |
|---|---|
| `TAPO_MCP_USERNAME` / `_PASSWORD` | TP-Link cloud account |
| `TAPO_MCP_CAMERA_USERNAME` / `_PASSWORD` | Camera Account from step 1 |
| `TAPO_MCP_DISCOVERY_TARGET` | LAN broadcast address |
| `TAPO_MCP_API_KEY` | random token (required — container binds `0.0.0.0`) |

## 3 · Run (Linux host)

```bash
podman-compose --profile tapo up -d tapo-mcp   # or: docker compose --profile tapo up -d tapo-mcp
podman logs -f tapo-mcp
```

`network_mode: host` is required for UDP discovery. On macOS/Windows Docker Desktop
discovery won't work — run it on a Linux box / Raspberry Pi on the same LAN instead,
or build natively: `cargo install tapo-mcp` then export the same env vars
(with `TAPO_MCP_HTTP_ADDR=127.0.0.1:3000`, the API key becomes optional).

## 4 · Connect Claude Code

`.mcp.json` at the repo root registers the server as `tapo`. It expands
`TAPO_MCP_API_KEY` from your shell, so export it before launching:

```bash
set -a; . ./.env; set +a
claude            # approve the "tapo" project MCP server when prompted
```

Or add it manually: `claude mcp add --transport http tapo http://localhost:3000/ --header "Authorization: Bearer $TAPO_MCP_API_KEY"`

If Claude runs on a different machine than the server, set
`TAPO_MCP_ALLOWED_HOSTS=<server-ip>:3000` in the compose env and point the URL at that IP.

## 5 · Try it

- "List all my Tapo devices"
- "Take a snapshot from the front door camera"
- "Get the device info for the living room camera"

## Troubleshooting

| Symptom | Fix |
|---|---|
| `list_devices` empty | wrong `TAPO_MCP_DISCOVERY_TARGET`; not using host network; camera on guest/IoT VLAN |
| `take_snapshot` auth error | camera-account creds unset/wrong; must be set per camera |
| `403 Forbidden` | `Host` header not in `TAPO_MCP_ALLOWED_HOSTS` |
| `401 Unauthorized` | missing/wrong Bearer token |
| container exits at start | `TAPO_MCP_API_KEY` empty |
