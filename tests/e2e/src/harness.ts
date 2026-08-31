// Spawns the real gateway (tsx) and the real sim (the venv's python, NOT the uv wrapper —
// signals must reach the executor itself) as child processes against Postgres. Readiness
// comes from the processes' own stable stdout lines (LISTENING/CONTROL/READY) via an
// accumulating buffer, so lines arriving in one chunk are never lost, plus /healthz polling.
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(here, "..", "..", "..");
const TSX_BIN = join(REPO_ROOT, "services", "gateway", "node_modules", ".bin", "tsx");
const SIM_PYTHON = join(REPO_ROOT, "tools", "revit-sim", ".venv", "bin", "python");
const CONVERTER_PYTHON = join(REPO_ROOT, "services", "scan-converter", ".venv", "bin", "python");

export const SERVICE_TOKEN = "service-token-0123456789";
export const ACTOR_TOKEN = "actor-token-eran";
export const ACTOR_EMAIL = "eran@hellochapter.com";

/** Accumulates a process's stdout so readiness lines are never lost between waiters. */
class Output {
  private text = "";
  private waiters: { prefix: string; resolve: (line: string) => void }[] = [];

  constructor(proc: ChildProcess) {
    proc.stdout?.on("data", (chunk: Buffer) => {
      this.text += chunk.toString();
      this.waiters = this.waiters.filter((w) => {
        const line = this.find(w.prefix);
        if (line !== null) {
          w.resolve(line);
          return false;
        }
        return true;
      });
    });
  }

  private find(prefix: string): string | null {
    for (const line of this.text.split("\n")) {
      if (line.startsWith(prefix)) return line.trim();
    }
    return null;
  }

  waitForLine(prefix: string, proc: ChildProcess, timeoutMs = 30_000): Promise<string> {
    const existing = this.find(prefix);
    if (existing !== null) return Promise.resolve(existing);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`timeout waiting for "${prefix}" from pid ${proc.pid}\n--- output ---\n${this.text}`)),
        timeoutMs,
      );
      proc.once("exit", (code) => {
        clearTimeout(timer);
        reject(new Error(`process exited (${code}) before "${prefix}"\n--- output ---\n${this.text}`));
      });
      this.waiters.push({
        prefix,
        resolve: (line) => {
          clearTimeout(timer);
          resolve(line);
        },
      });
    });
  }
}

export interface GatewayProc {
  port: number;
  url: string;
  proc: ChildProcess;
}

export interface SimProc {
  proc: ChildProcess;
  controlPort: number | null;
  stateDir: string;
  ready: Promise<void>;
}

export async function startGateway(
  databaseUrl: string,
  extraEnv: Record<string, string> = {},
): Promise<GatewayProc> {
  const proc = spawn(TSX_BIN, ["src/main.ts"], {
    cwd: join(REPO_ROOT, "services", "gateway"),
    env: {
      ...process.env,
      PORT: "0",
      DATABASE_URL: databaseUrl,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN,
      ACTOR_TOKENS: `${ACTOR_TOKEN}:${ACTOR_EMAIL}`,
      LOG_LEVEL: "warn",
      ...extraEnv,
    },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const output = new Output(proc);
  const line = await output.waitForLine("LISTENING ", proc);
  const port = Number(line.split(" ")[1]);

  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (res.ok) break;
    } catch {
      /* not up yet */
    }
    await sleep(100);
  }
  return { port, url: `http://127.0.0.1:${port}`, proc };
}

export interface ConverterProc {
  port: number;
  url: string;
  proc: ChildProcess;
}

/** Third child process of the Phase 2 suite: the real scan-converter service.
 *  It binds port 0 itself and prints "LISTENING <port>" before uvicorn starts. */
export async function startConverter(): Promise<ConverterProc> {
  const proc = spawn(CONVERTER_PYTHON, ["-m", "scan_converter", "--serve", "--port", "0"], {
    cwd: join(REPO_ROOT, "services", "scan-converter"),
    env: { ...process.env, PYTHONPATH: join(REPO_ROOT, "services", "scan-converter", "src") },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const output = new Output(proc);
  const line = await output.waitForLine("LISTENING ", proc);
  const port = Number(line.split(" ")[1]);
  return { port, url: `http://127.0.0.1:${port}`, proc };
}

export function startSim(
  gatewayPort: number,
  token: string,
  opts: { stateDir?: string; controlPort?: boolean; workstationId?: string } = {},
): SimProc {
  const stateDir = opts.stateDir ?? mkdtempSync(join(tmpdir(), "sim-"));
  const args = [
    "-m", "revit_sim",
    "--gateway-url", `ws://127.0.0.1:${gatewayPort}/wss`,
    "--token", token,
    "--workstation-id", opts.workstationId ?? "ws-design-01",
    "--state-dir", join(stateDir, "state"),
    "--blob-dir", join(stateDir, "blobs"),
  ];
  if (opts.controlPort) args.push("--control-port", "0");
  const proc = spawn(SIM_PYTHON, args, {
    cwd: join(REPO_ROOT, "tools", "revit-sim"),
    env: { ...process.env, PYTHONPATH: join(REPO_ROOT, "tools", "revit-sim", "src") },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const output = new Output(proc);

  const sim: SimProc = { proc, controlPort: null, stateDir, ready: Promise.resolve() };
  sim.ready = (async () => {
    if (opts.controlPort) {
      const control = await output.waitForLine("CONTROL ", proc);
      sim.controlPort = Number(control.split(" ")[1]);
    }
    await output.waitForLine("READY", proc);
  })();
  return sim;
}

export async function controlCommand(port: number, command: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const socket = createConnection({ host: "127.0.0.1", port }, () => {
      socket.write(command + "\n");
    });
    let data = "";
    socket.on("data", (chunk) => (data += chunk.toString()));
    socket.on("end", () => resolve(data.trim()));
    socket.on("error", reject);
  });
}

export function stop(proc: ChildProcess, signal: NodeJS.Signals = "SIGTERM"): Promise<void> {
  return new Promise((resolve) => {
    if (proc.exitCode !== null || proc.signalCode !== null) return resolve();
    proc.once("exit", () => resolve());
    proc.kill(signal);
    setTimeout(() => {
      if (proc.exitCode === null && proc.signalCode === null) proc.kill("SIGKILL");
    }, 5_000).unref();
  });
}

export function cleanupDir(dir: string): void {
  rmSync(dir, { recursive: true, force: true });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
