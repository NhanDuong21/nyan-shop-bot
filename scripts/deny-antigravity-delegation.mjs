// NYAN-ANTIGRAVITY-SINGLE-WRITER-V1: fail-closed PreToolUse handler.

import fs from "node:fs";
import path from "node:path";

const executionTools = new Set([
  "run_command",
  "manage_task",
  "schedule",
  "ask_permission",
  "invoke_subagent",
  "define_subagent",
  "send_message",
  "manage_subagents",
  "browser_subagent",
  "command_status",
  "send_command_input",
  "call_mcp_tool",
]);
const writeTools = new Set([
  "write_to_file",
  "replace_file_content",
  "multi_replace_file_content",
]);
const protectedPaths = new Set([
  "AGENTS.md",
  "agents.md",
  ".agents/hooks.json",
  ".agents/rules/ui-worker.md",
  "scripts/deny-antigravity-delegation.mjs",
]);

let input = "";
for await (const chunk of process.stdin) {
  input += chunk;
}

function emit(decision, reason) {
  process.stdout.write(`${JSON.stringify({ decision, reason })}\n`);
}

function normalized(value) {
  const absolute = path.resolve(value).replaceAll("\\", "/");
  return process.platform === "win32" ? absolute.toLowerCase() : absolute;
}

function unsafeWindowsAlias(value) {
  const slashPath = value.replaceAll("\\", "/");
  if (/^[A-Za-z]:($|[^/])/.test(slashPath) || slashPath.startsWith("//")) {
    return true;
  }
  const withoutDrive = /^[A-Za-z]:\//.test(slashPath) ? slashPath.slice(2) : slashPath;
  if (withoutDrive.includes(":")) {
    return true;
  }
  return slashPath
    .split("/")
    .filter((segment) => segment.length > 0)
    .some((segment) => segment.endsWith(".") || segment.endsWith(" "));
}

function canonicalPath(value) {
  let existing = path.resolve(value);
  const missingSegments = [];
  while (!fs.existsSync(existing)) {
    const parent = path.dirname(existing);
    if (parent === existing) {
      throw new Error("No existing ancestor for hook path");
    }
    missingSegments.unshift(path.basename(existing));
    existing = parent;
  }
  const canonicalAncestor = fs.realpathSync.native(existing);
  return normalized(path.join(canonicalAncestor, ...missingSegments));
}

function relativeToWorkspace(target, workspace) {
  const relative = path.relative(workspace, target).replaceAll("\\", "/");
  if (relative === "" || relative === ".." || relative.startsWith("../") || path.isAbsolute(relative)) {
    return null;
  }
  return process.platform === "win32" ? relative.toLowerCase() : relative;
}

let request;
try {
  request = JSON.parse(input);
} catch {
  emit("deny", "Malformed Nyan hook request; fail closed.");
  process.exit(0);
}

const toolName = request?.toolCall?.name;
if (executionTools.has(toolName)) {
  emit(
    "deny",
    "Nyan UI tasks permit exactly one Antigravity writer; shell, background, " +
      "permission-escalation, scheduling, and delegation tools are disabled before execution.",
  );
  process.exit(0);
}

if (!writeTools.has(toolName)) {
  emit("deny", "Unexpected tool matched the Nyan safety hook; fail closed.");
  process.exit(0);
}

const targetFile = request?.toolCall?.args?.TargetFile;
const workspacePaths = Array.isArray(request?.workspacePaths) ? request.workspacePaths : [];
if (typeof targetFile !== "string" || targetFile.length === 0 || workspacePaths.length === 0) {
  emit("deny", "Write request omitted its target or workspace; fail closed.");
  process.exit(0);
}
if (unsafeWindowsAlias(targetFile)) {
  emit("deny", "Windows device, UNC, drive-relative, stream, or ambiguous paths are disabled.");
  process.exit(0);
}

let permittedWorkspaceWrite = false;
for (const rawWorkspace of workspacePaths) {
  if (typeof rawWorkspace !== "string" || rawWorkspace.length === 0) {
    continue;
  }
  let workspace;
  let target;
  try {
    workspace = canonicalPath(rawWorkspace);
    target = canonicalPath(
      path.isAbsolute(targetFile) ? targetFile : path.join(workspace, targetFile),
    );
  } catch {
    emit("deny", "Write target could not be canonicalized; fail closed.");
    process.exit(0);
  }
  const relative = relativeToWorkspace(target, workspace);
  if (relative === null) {
    continue;
  }
  permittedWorkspaceWrite = true;
  const rootName = relative.includes("/") ? "" : relative;
  const executableShim =
    rootName === "node" ||
    rootName.startsWith("node.") ||
    rootName === "cmd" ||
    rootName.startsWith("cmd.") ||
    rootName === "powershell" ||
    rootName.startsWith("powershell.") ||
    rootName === "pwsh" ||
    rootName.startsWith("pwsh.") ||
    rootName === "sh" ||
    rootName === "bash";
  if (
    protectedPaths.has(relative) ||
    relative.startsWith(".agents/") ||
    executableShim
  ) {
    emit("deny", "The trusted Nyan hook, rule, handler, or command resolver is immutable.");
    process.exit(0);
  }
}

if (!permittedWorkspaceWrite) {
  emit("deny", "Writes outside the mounted workspace are disabled.");
  process.exit(0);
}

emit("allow", "Workspace write does not target the trusted Nyan execution guard.");
