// =============================================================================
// bash-executor.js — Spawn a bash script and pipe neutral JSON context to stdin
// =============================================================================
// This file is vendored verbatim into the generated mbifc-hooks.js plugin at
// build time. It must not require any npm modules beyond Node.js builtins so
// that opencode's embedded runtime can execute it without installation.
// =============================================================================
const { spawn } = require("node:child_process");

/**
 * Run a bash script with a JSON payload on stdin.
 *
 * @param {string} scriptPath  Absolute path to the .sh file.
 * @param {object} payload     Neutral-schema object to pipe in as JSON.
 * @param {object} [env]       Extra environment variables (merged with process.env).
 * @returns {Promise<{exitCode:number, stdout:string, stderr:string}>}
 */
function runBashHook(scriptPath, payload, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("bash", [scriptPath], {
      env: { ...process.env, ...env },
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => { stdout += d.toString(); });
    child.stderr.on("data", (d) => { stderr += d.toString(); });
    child.on("error", reject);
    child.on("close", (exitCode) => {
      resolve({ exitCode: exitCode ?? 0, stdout, stderr });
    });

    try {
      child.stdin.write(JSON.stringify(payload));
      child.stdin.end();
    } catch (err) {
      reject(err);
    }
  });
}

module.exports = { runBashHook };
