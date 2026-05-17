# interactsh-mcp

An MCP server that gives LLMs first-class access to [ProjectDiscovery's
Interactsh](https://github.com/projectdiscovery/interactsh) — the out-of-band
(OOB) interaction collector behind tools like Nuclei.

Use it to let an agent validate OOB-style vulnerabilities end-to-end: blind
SSRF, log4shell-style JNDI callbacks, blind XXE, blind SQLi exfil, DNS
exfiltration, command-injection callbacks, blind XSS, etc. The agent gets a
fresh payload URL, embeds it in a request to the target, and polls for the
callback to confirm the bug.

Works against the **public** Interactsh service (the public `oast.*`
rotation) out of the box, and against any **self-hosted** server — with or
without a token.

---

## Install

### From PyPI (recommended)

```bash
pip install interactsh-mcp
# or, with uv:
uv tool install interactsh-mcp
```

After install the `interactsh-mcp` command starts the MCP server on stdio.

### From GitHub (latest, no PyPI release needed)

```bash
pip install git+https://github.com/rek7/interactsh-mcp.git
# or, run without installing:
uvx --from git+https://github.com/rek7/interactsh-mcp.git interactsh-mcp
```

### From source

```bash
git clone https://github.com/rek7/interactsh-mcp.git
cd interactsh-mcp
pip install .
```

### Docker

```bash
# Build locally
docker build -t interactsh-mcp .
docker run --rm -i interactsh-mcp     # smoke test; Ctrl-D to exit
```

The image runs as a non-root user and only needs outbound HTTPS to the
Interactsh server.

---

## Configure your client

### Claude Code

Claude Code reads MCP servers from `~/.claude.json` (or a project-local
`.mcp.json`). Add an entry under `"mcpServers"`:

**Local Python install — public servers**

```jsonc
{
  "mcpServers": {
    "interactsh": {
      "command": "interactsh-mcp"
    }
  }
}
```

**Local Python install — self-hosted server**

```jsonc
{
  "mcpServers": {
    "interactsh": {
      "command": "interactsh-mcp",
      "env": {
        "INTERACTSH_SERVER": "interact.example.com",
        "INTERACTSH_TOKEN": "your-server-token"
      }
    }
  }
}
```

Omit `INTERACTSH_TOKEN` if your self-hosted server was started without
`-auth`.

**Docker**

```jsonc
{
  "mcpServers": {
    "interactsh": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "INTERACTSH_SERVER",
        "-e", "INTERACTSH_TOKEN",
        "interactsh-mcp"
      ],
      "env": {
        "INTERACTSH_SERVER": "interact.example.com",
        "INTERACTSH_TOKEN": "your-server-token"
      }
    }
  }
}
```

You can also register the server with the CLI:

```bash
claude mcp add interactsh -- interactsh-mcp
# with env vars:
claude mcp add interactsh \
  -e INTERACTSH_SERVER=interact.example.com \
  -e INTERACTSH_TOKEN=your-server-token \
  -- interactsh-mcp
```

### Codex CLI

Codex CLI (OpenAI's terminal coding agent) reads MCP servers from
`~/.codex/config.toml`:

**Public servers**

```toml
[mcp_servers.interactsh]
command = "interactsh-mcp"
```

**Self-hosted with token**

```toml
[mcp_servers.interactsh]
command = "interactsh-mcp"
env = { INTERACTSH_SERVER = "interact.example.com", INTERACTSH_TOKEN = "your-server-token" }
```

**Docker**

```toml
[mcp_servers.interactsh]
command = "docker"
args = ["run", "--rm", "-i", "-e", "INTERACTSH_SERVER", "-e", "INTERACTSH_TOKEN", "interactsh-mcp"]
env = { INTERACTSH_SERVER = "interact.example.com", INTERACTSH_TOKEN = "your-server-token" }
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows. Same shape as the
Claude Code example above.

---

## Environment variables

| Variable | Purpose |
| --- | --- |
| `INTERACTSH_SERVER` | Default hostname (e.g. `interact.example.com`). If unset, a random host from the public `oast.*` rotation is used. Per-call `server` argument overrides. |
| `INTERACTSH_TOKEN` | Default Authorization token for `-auth`-protected servers. Per-call `token` argument overrides. |
| `INTERACTSH_LOG_LEVEL` | Python log level (default `WARNING`). |

---

## Tools the LLM sees

| Tool | What it does |
| --- | --- |
| `create_session` | Registers a new Interactsh session, starts background polling, and returns `session_id` + `payload_url`. Optional args: `server`, `token`, `poll_interval`, `scheme`, `correlation_id_length`. |
| `list_sessions` | Lists active sessions with their buffer counts. |
| `poll_interactions` | Drains buffered interactions for a session. `wait` (seconds) blocks until the first event arrives; `clear=false` peeks without consuming. |
| `new_payload` | Vends an additional payload URL on an existing session (different nonce, same correlation-id — all routed back to the same session). |
| `destroy_session` | Deregisters and frees the session. |
| `get_default_servers` | Returns the public `oast.*` host list. |

---

## Typical agent workflow

1. Agent calls `create_session` → gets `payload_url` e.g.
   `c7lci09s8mts0o3og0g0abc12.oast.pro`.
2. Agent crafts an exploit that uses `payload_url` — a JNDI string in a User-Agent
   header, a `?url=http://payload_url/` SSRF, a DNS subdomain in a SQL payload,
   etc.
3. Agent sends the request to the target.
4. Agent calls `poll_interactions(session_id, wait=10)` and, if interactions
   come back, reports the vuln as confirmed (with the source IP / raw request
   from the callback as evidence).
5. Agent calls `destroy_session` when done.

For multiple test variants in one conversation the agent can either call
`create_session` per variant or call `new_payload` to get distinct URLs that
share a session.

---

## Self-hosting Interactsh

Quick reminder of how to stand up a server you can point this MCP at:

```bash
# Public, no auth:
interactsh-server -domain interact.example.com

# Token-protected (server prints a random token; pass it as INTERACTSH_TOKEN):
interactsh-server -domain interact.example.com -auth
```

See the [interactsh server docs](https://github.com/projectdiscovery/interactsh#interactsh-server)
for DNS, TLS, and infra setup.

---

## Development

```bash
git clone https://github.com/rek7/interactsh-mcp.git
cd interactsh-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
pytest
```

Live integration tests (DNS-callback against a real server) are opt-in:

```bash
INTERACTSH_LIVE=1 pytest tests/test_live.py
# or against a self-hosted server:
INTERACTSH_LIVE=1 INTERACTSH_SERVER=interact.example.com INTERACTSH_TOKEN=... pytest tests/test_live.py
```

The mocked test suite exercises the full register → poll → decrypt → drain
path against an in-process fake server, so the crypto and HTTP wiring are
covered without network access.

---

## License

MIT. Interactsh itself is MIT-licensed and developed by
[ProjectDiscovery](https://projectdiscovery.io/).
