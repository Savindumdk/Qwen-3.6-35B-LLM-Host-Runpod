# MCP servers (Playwright · GitHub · Filesystem · PostgreSQL)

## Where MCP fits

MCP servers connect to the **client** (Zoo Code), not to the gateway or the
model. They run as local processes on **your PC**. The flow is:

```
Zoo Code  ──(MCP, stdio/http)──>  MCP servers on your PC (Playwright, GitHub, …)
   │
   └──(OpenAI API)──>  Gateway ──> Engine ──> Qwen3.6-35B-A3B
```

Zoo Code decides *when* to call a tool, asks the **model** to produce a tool call
(OpenAI function-calling — which this stack fully supports), then executes that
call against the relevant MCP server and feeds the result back to the model. So
the only requirement on the server side is **working tool calling**, which the
engine provides (llama.cpp `--jinja` / vLLM `--enable-auto-tool-choice`).

## Configure servers in Zoo Code

In Zoo Code: **Settings → MCP Servers → Edit Global MCP** (writes
`mcp_settings.json`), or create **`.roo/mcp.json`** in your project root to share
config with a team. Both use the same schema:

```jsonc
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Epic"],
      "alwaysAllow": ["read_file", "list_directory"]
    },

    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_PAT}" }
    },

    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    },

    "postgres": {
      "command": "npx",
      "args": [
        "-y", "@modelcontextprotocol/server-postgres",
        "postgresql://user:pass@localhost:5432/mydb"
      ]
    }
  }
}
```

Notes:
- **Prerequisites**: Node.js (for `npx`). Playwright will download a browser on
  first run.
- **Secrets**: prefer `${env:VAR}` substitution (e.g. `GITHUB_PAT`) over inline
  tokens; set the variable in your OS environment before launching VS Code.
- **`alwaysAllow`**: lists tools that won't prompt for confirmation each call —
  keep it to read-only tools you trust.
- **Windows paths**: escape backslashes in JSON (`C:\\Epic`).
- **Remote MCP** (Streamable HTTP) instead of stdio:
  ```jsonc
  "my-remote": { "type": "streamable-http", "url": "http://localhost:8080/mcp",
                 "headers": { "Authorization": "Bearer ${env:MY_TOKEN}" } }
  ```
  Prefer Streamable HTTP over legacy SSE for new remote servers.

## Recommended sampling for agentic/tool use

Tool-using agents are most reliable with lower-temperature decoding. In Zoo
Code's profile set **Temperature ≈ 0.6** (Qwen's thinking-coding preset:
`top_p 0.95, top_k 20, presence_penalty 0`). Higher temperatures make the model
more likely to malform tool-call arguments.

## Server references

| Server      | Package                                          |
|-------------|--------------------------------------------------|
| Filesystem  | `@modelcontextprotocol/server-filesystem`        |
| GitHub      | `@modelcontextprotocol/server-github` (or GitHub's official MCP server) |
| Playwright  | `@playwright/mcp`                                |
| PostgreSQL  | `@modelcontextprotocol/server-postgres`          |

Some reference servers evolve / get superseded by official vendor servers; if a
package is unavailable, check its homepage for the current replacement. The Zoo
Code config schema above is unchanged regardless of which server binary you use.
