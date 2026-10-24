// =============================================================================
// HYDRA-UMC-BRIDGE-OPENPNP - Runs an OpenPnP script outside OpenPnP (test fixture)
// Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
// GPL-3.0-or-later - see LICENSE
// =============================================================================
// usage: node openpnp_script_harness.js SCRIPT STATE_FILE [machine=busy|idle|disabled|broken] [job=NAME] [nojob]
//
// OpenPnP runs these scripts on a JVM, where `Java.type(...)` gives the Java classes. This harness gives the scripts the few
// Java classes they use, built on Node's `fs`, so that what they write can be read by the Python bridge in the tests. It
// also gives the globals OpenPnP gives them (`machine`, `job`). It proves the logic and the file format of the scripts, not
// that OpenPnP fires the events.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [scriptPath, stateFile, ...options] = process.argv.slice(2);
const flags = Object.fromEntries(options.map((o) => (o.includes("=") ? o.split("=", 2) : [o, true])));

class JPath {
  constructor(p) { this.p = p; }
  getParent() { const d = path.dirname(this.p); return d === this.p || d === "." ? null : new JPath(d); }
  toString() { return this.p; }
}
const javaStrings = {
  // new JString(bytes, "UTF-8") and new JString(text).getBytes("UTF-8")
  create: function (value) {
    const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
    return { toString: () => text, getBytes: () => Buffer.from(text, "utf8"), length: () => text.length };
  },
};
function JString(value) { return javaStrings.create(value); }

const classes = {
  "java.lang.System": {
    getenv: (name) => (name === "HYDRA_UMC_OPENPNP_STATE_FILE" ? stateFile : null),
    getProperty: () => path.dirname(stateFile),
    currentTimeMillis: () => Date.now(),
  },
  "java.nio.file.Files": {
    exists: (p) => fs.existsSync(p.p),
    createDirectories: (p) => fs.mkdirSync(p.p, { recursive: true }),
    readAllBytes: (p) => fs.readFileSync(p.p),
    write: (p, bytes) => fs.writeFileSync(p.p, bytes),
    move: (from, to) => fs.renameSync(from.p, to.p),
  },
  "java.nio.file.Paths": { get: (p) => new JPath(String(p)) },
  "java.nio.file.StandardCopyOption": { REPLACE_EXISTING: 1, ATOMIC_MOVE: 2 },
  "java.lang.String": JString,
};

const context = {
  Java: { type: (name) => { if (!(name in classes)) throw new Error("class not provided: " + name); return classes[name]; } },
  JSON, Number, String,
};
const machineMode = flags.machine || "idle";
context.machine = {
  isEnabled: () => { if (machineMode === "broken") throw new Error("no machine"); return machineMode !== "disabled"; },
  isBusy: () => machineMode === "busy",
};
if (!flags.nojob) {
  context.job = { getFile: () => ({ getName: () => String(flags.job || "board.job.xml") }) };
}
vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), context, { filename: scriptPath });
