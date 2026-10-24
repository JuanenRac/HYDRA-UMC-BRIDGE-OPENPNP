// =============================================================================
// HYDRA-UMC-BRIDGE-OPENPNP - OpenPnP event script: Machine.AfterHoming
// Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
// GPL-3.0-or-later - see LICENSE
// =============================================================================
// Copy this folder's files to the Events folder of the OpenPnP scripts directory
// (menu: Scripts > Open Scripts Directory > Events). OpenPnP runs a script named
// after an event when that event happens.
//
// The machine has homed and nothing runs on it.
//
// It does not call enable(), home(), moveTo(), actuate(), feeder actions, or write any
// OpenPnP configuration. It writes ONE small JSON file, atomically (temporary file, then
// move), that HYDRA-UMC-BRIDGE-OPENPNP reads as the observed state of the machine:
//   {"origin":"openpnp-events","generation":N,"observed_at_ms":T,"event":"Machine.AfterHoming",
//    "job":"<job file name>","machine_state":"IDLE"}
// The file is ~/.openpnp2/hydra-umc/openpnp_state.json unless the environment variable
// HYDRA_UMC_OPENPNP_STATE_FILE names another path (the bridge reads the same variable).
// A failure to write is swallowed on purpose: a script must never stop a job, and the
// bridge treats an old or missing file as "state unknown", which refuses work.

(function () {
    try {
        var System = Java.type("java.lang.System");
        var Files = Java.type("java.nio.file.Files");
        var Paths = Java.type("java.nio.file.Paths");
        var StandardCopyOption = Java.type("java.nio.file.StandardCopyOption");
        var JString = Java.type("java.lang.String");

        var configured = System.getenv("HYDRA_UMC_OPENPNP_STATE_FILE");
        var path = Paths.get(configured !== null && String(configured).length > 0
            ? String(configured)
            : String(System.getProperty("user.home")) + "/.openpnp2/hydra-umc/openpnp_state.json");
        if (path.getParent() !== null) {
            Files.createDirectories(path.getParent());
        }

        // the generation only ever grows, so that a replayed old file can be told from a new reading
        var generation = 1;
        try {
            if (Files.exists(path)) {
                var previous = JSON.parse(String(new JString(Files.readAllBytes(path), "UTF-8")));
                if (typeof previous.generation === "number" && previous.generation >= 0) {
                    generation = previous.generation + 1;
                }
            }
        } catch (ignored) {
            generation = 1;
        }

        var jobName = "";
        // this event has no job in scope

        var state = {
            origin: "openpnp-events",
            generation: generation,
            observed_at_ms: Number(System.currentTimeMillis()),
            event: "Machine.AfterHoming",
            job: jobName,
            machine_state: "IDLE"
        };
        var temporary = Paths.get(path.toString() + ".tmp");
        Files.write(temporary, new JString(JSON.stringify(state)).getBytes("UTF-8"));
        Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    } catch (ignored) {
        // see the header: never let this script get in the way of OpenPnP
    }
})();
