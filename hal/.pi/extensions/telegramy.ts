/**
 * Pi extension that bridges to the telegramy MCP server via HTTP.
 *
 * Expects the MCP server to be already running (e.g. started with
 * ``start_mcp.bat`` or ``python -m src.main`` with TELEGRAMY_MCP_TRANSPORT=http).
 * Discovers MCP tools and registers them as pi custom tools.
 *
 * Set TELEGRAMY_DEBUG=true to enable verbose request/response logging.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

// ── debug toggle ──────────────────────────────────────────

const DEBUG = process.env.TELEGRAMY_DEBUG === "true";

function debugLog(...args: unknown[]): void {
  if (DEBUG) console.error(...args);
}

// ── MCP JSON-RPC types ──────────────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

interface McpToolProp {
  type?: string;
  description?: string;
  // FastMCP emits Optional[T] as anyOf: [{T}, {"type":"null"}].
  anyOf?: McpToolProp[];
  oneOf?: McpToolProp[];
  // Array items schema.
  items?: McpToolProp;
  // Permissive object (arbitrary dict, e.g. reply_markup).
  additionalProperties?: boolean;
  default?: unknown;
}

interface McpToolDef {
  name: string;
  description?: string;
  inputSchema: {
    type: "object";
    properties?: Record<string, McpToolProp>;
    required?: string[];
  };
}

type PendingRequest = {
  resolve: (res: JsonRpcResponse) => void;
  reject: (err: Error) => void;
  method: string;
  startedAt: number;
  timeoutMs: number;
  timer: ReturnType<typeof setTimeout>;
  abortHandler?: () => void;
  signal?: AbortSignal;
};

// ── MCP Client over HTTP ───────────────────────────────────────

class McpHttpClient {
  private requestId = 0;
  private pending = new Map<number, PendingRequest>();
  private connected = false;
  private baseUrl: string;
  private sessionId: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async start(): Promise<void> {
    // Send initialize directly (not via request()) so we can capture the
    // mcp-session-id from response headers. FastMCP 3.x streamable-http
    // requires this header on every request after initialize.
    const initResponse = await fetch(this.baseUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 0,
        method: "initialize",
        params: {
          protocolVersion: "2024-11-05",
          capabilities: {},
          clientInfo: { name: "pi-telegramy", version: "1.0.0" },
        },
      }),
    });

    if (!initResponse.ok) {
      throw new Error(
        `MCP initialize failed: HTTP ${initResponse.status} ${initResponse.statusText}`
      );
    }

    const sid = initResponse.headers.get("mcp-session-id");
    if (sid) {
      this.sessionId = sid;
      debugLog(`telegramy: captured session ID ${sid.slice(0, 8)}…`);
    }

    // Drain the initialize response body to free the connection
    await initResponse.text();

    // MCP spec: server waits for initialized notification before processing requests
    await this.sendNotification("notifications/initialized", {});
    this.connected = true;
  }

  isConnected(): boolean {
    return this.connected;
  }

  async listTools(): Promise<McpToolDef[]> {
    const res = await this.request("tools/list", {});
    return (res.result as { tools: McpToolDef[] })?.tools ?? [];
  }

  async callTool(
    name: string,
    args: Record<string, unknown>,
    signal?: AbortSignal
  ): Promise<string> {
    const res = await this.request(
      "tools/call",
      { name, arguments: args },
      signal
    );
    const content = (
      res.result as { content?: Array<{ type: string; text?: string }> }
    )?.content;
    if (content && content.length > 0) {
      return content.map((c) => c.text ?? "").join("\n");
    }
    return JSON.stringify(res.result);
  }

  private request(
    method: string,
    params: Record<string, unknown>,
    signal?: AbortSignal
  ): Promise<JsonRpcResponse> {
    const id = ++this.requestId;
    const timeoutMs = this.timeoutFor(method);
    const startedAt = Date.now();

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        const elapsed = Date.now() - startedAt;
        reject(
          new Error(
            `MCP request timeout after ${elapsed}ms (configured ${timeoutMs}ms): ${method}`
          )
        );
      }, timeoutMs);

      const abortHandler = () => {
        cleanup();
        const elapsed = Date.now() - startedAt;
        reject(
          new Error(`MCP request cancelled after ${elapsed}ms: ${method}`)
        );
      };

      const cleanup = () => {
        this.pending.delete(id);
        clearTimeout(timer);
        if (signal && abortHandler) {
          signal.removeEventListener("abort", abortHandler);
        }
      };

      if (signal?.aborted) {
        clearTimeout(timer);
        reject(new Error(`MCP request cancelled before send: ${method}`));
        return;
      }

      if (signal) {
        signal.addEventListener("abort", abortHandler, { once: true });
      }

      this.pending.set(id, {
        resolve: (res: JsonRpcResponse) => {
          cleanup();
          if (res.error) reject(new Error(res.error.message));
          else resolve(res);
        },
        reject,
        method,
        startedAt,
        timeoutMs,
        timer,
        abortHandler: signal ? abortHandler : undefined,
        signal,
      });

      debugLog(`telegramy MCP ${method} started (timeout ${timeoutMs}ms)`);

      this.sendHttp(id, method, params)
        .then((response) => {
          const pending = this.pending.get(id);
          if (pending) {
            const elapsed = Date.now() - pending.startedAt;
            debugLog(
              `telegramy MCP ${pending.method} completed in ${elapsed}ms`
            );
            pending.resolve(response);
          }
        })
        .catch((err) => {
          const pending = this.pending.get(id);
          if (pending) {
            pending.reject(err);
          }
        });
    });
  }

  private requestHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    };
    if (this.sessionId) {
      headers["mcp-session-id"] = this.sessionId;
    }
    return headers;
  }

  private async sendHttp(
    id: number,
    method: string,
    params: Record<string, unknown>
  ): Promise<JsonRpcResponse> {
    const body: JsonRpcRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    const response = await fetch(this.baseUrl, {
      method: "POST",
      headers: this.requestHeaders(),
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(
        `MCP HTTP error ${response.status}: ${response.statusText}`
      );
    }

    const text = await response.text();
    const sseBody = this.parseStreamableHttp(text);
    if (!sseBody) {
      return { jsonrpc: "2.0", id, result: {} };
    }
    return JSON.parse(sseBody) as JsonRpcResponse;
  }

  private parseStreamableHttp(text: string): string | null {
    // FastMCP streamable-http returns SSE: "event: message\ndata: {...}\n\n"
    // Plain JSON is also accepted as fallback.
    if (text.startsWith("{")) {
      return text;
    }
    const lines = text.split("\n");
    for (const line of lines) {
      if (line.startsWith("data:")) {
        return line.slice(5).trim();
      }
    }
    return null;
  }

  private async sendNotification(
    method: string,
    params: Record<string, unknown>
  ): Promise<void> {
    const body = { jsonrpc: "2.0", method, params };
    const response = await fetch(this.baseUrl, {
      method: "POST",
      headers: this.requestHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok && response.status !== 202) {
      debugLog(`telegramy: notification ${method} got HTTP ${response.status}`);
    }
  }

  private timeoutFor(method: string): number {
    if (method === "tools/call") return 300000;
    if (method === "initialize" || method === "tools/list") return 30000;
    return 30000;
  }
}

// ── JSON schema → TypeBox helper ───────────────────────────────

/** Resolve a JSON-schema property to a TypeBox schema.
 *
 * Handles the subset FastMCP emits: scalars, arrays (with typed items),
 * arbitrary objects (reply_markup), and Optional[T] expressed as
 * anyOf/oneOf [{T}, {"type":"null"}] (we pick the non-null member).
 * Unknown types degrade to Type.String so registration never throws.
 */
function propToTypeBox(prop: McpToolProp): unknown {
  const description = prop.description;

  // Unwrap anyOf/oneOf by picking the first non-null member (Optional[T]).
  let effective = prop;
  const union = prop.anyOf ?? prop.oneOf;
  if (union && union.length > 0) {
    const nonNull = union.find((m) => m.type !== "null");
    if (nonNull) effective = { ...nonNull, description };
  }

  const typ = effective.type ?? "string";
  switch (typ) {
    case "integer":
    case "number":
      return Type.Number({ description });
    case "boolean":
      return Type.Boolean({ description });
    case "array": {
      const items = effective.items;
      const itemSchema =
        items && items.type ? (propToTypeBox(items) as unknown) : Type.String();
      return Type.Array(itemSchema as never, { description });
    }
    case "object":
      // Arbitrary dict (e.g. reply_markup inline keyboard). Allow any keys.
      return Type.Object({}, { additionalProperties: true, description });
    case "string":
    default:
      return Type.String({ description });
  }
}

function jsonSchemaToTypeBox(schema: McpToolDef["inputSchema"]) {
  const shape: Record<string, unknown> = {};
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  for (const [key, prop] of Object.entries(props)) {
    const resolved = propToTypeBox(prop);
    // Mark truly optional params as Optional; required params stay required so
    // the model knows it must supply them (e.g. chunks).
    shape[key] = required.has(key) ? resolved : Type.Optional(resolved as never);
  }

  return Type.Object(shape);
}

// ── .env reader ────────────────────────────────────────────────
// pi does not auto-load .env, so we read the project .env ourselves to keep
// the MCP host/port in ONE place — the same file Python's load_dotenv() reads.
// Precedence: explicit process env > .env TELEGRAMY_MCP_URL >
// .env host:port > built-in default.

const MCP_PATH = "/mcp";

function parseEnvFile(filePath: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (!existsSync(filePath)) return out;
  const text = readFileSync(filePath, "utf8");
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function resolveMcpUrl(): string {
  // 1. Explicit env var (shell / pi config) wins outright.
  if (process.env.TELEGRAMY_MCP_URL) {
    return process.env.TELEGRAMY_MCP_URL.replace(/\/$/, "");
  }

  // 2. Read the project .env — same file src/main.py loads.
  const env = parseEnvFile(join(process.cwd(), ".env"));

  // 3. Full URL override in .env beats host/port composition.
  if (env.TELEGRAMY_MCP_URL) {
    return env.TELEGRAMY_MCP_URL.replace(/\/$/, "");
  }

  // 4. Compose from host/port, falling back to the python default.
  const host = env.TELEGRAMY_MCP_HOST || "127.0.0.1";
  const port = env.TELEGRAMY_MCP_PORT || "8005";
  return `http://${host}:${port}${MCP_PATH}`;
}

// ── Extension entry point ──────────────────────────────────────

export default async function (pi: ExtensionAPI) {
  const baseUrl = resolveMcpUrl();
  debugLog(`telegramy: resolved MCP URL ${baseUrl}`);
  const client = new McpHttpClient(baseUrl);

  pi.on("session_start", async (_event, ctx) => {
    try {
      ctx.ui.notify(
        `telegramy: Connecting to MCP server at ${baseUrl}...`,
        "info"
      );
      if (!client.isConnected()) {
        await client.start();
      }
      const tools = await client.listTools();
      ctx.ui.notify(
        `telegramy: Connected, ${tools.length} tools discovered`,
        "success"
      );

      for (const tool of tools) {
        const paramsSchema = jsonSchemaToTypeBox(tool.inputSchema);

        pi.registerTool({
          name: tool.name,
          label: tool.name,
          description: tool.description ?? `telegramy tool: ${tool.name}`,
          parameters: paramsSchema,
          async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
            try {
              const result = await client.callTool(
                tool.name,
                params as Record<string, unknown>,
                signal
              );
              return {
                content: [{ type: "text" as const, text: result }],
                details: {},
              };
            } catch (err) {
              return {
                content: [
                  {
                    type: "text" as const,
                    text: `telegramy error: ${
                      err instanceof Error ? err.message : String(err)
                    }`,
                  },
                ],
                details: {},
              };
            }
          },
        });

        ctx.ui.notify(`telegramy: Registered tool '${tool.name}'`, "info");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      ctx.ui.notify(
        `telegramy: ${msg}. Is the server running? Start it with:\n` +
          `  start_mcp.bat   (or)   .venv\\Scripts\\python.exe -m src.main`,
        "error"
      );
    }
  });
}
