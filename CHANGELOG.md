<!-- =============================================================================
HYDRA-UMC-BRIDGE-OPENPNP - Change history
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

# Changelog

## [0.0.1]

- Added traceable PCB hand-off coordinator, SDK safety gate and local tests.
- Added non-mutating build-test scripts and CI SDK checkout.
- Standardized README (all 7 languages) and project banner to match the
  rest of the ecosystem's established-project structure.
- Fixed a latent crash risk: `BoardFlow.plan()` looked up a job's handoff
  label with a plain dict index, which would raise an unhandled
  `KeyError` for any `JobPhase` the shared SDK might add in the future
  without this bridge's own handoff table being updated in lockstep. Now
  falls back to a real `"unrecognized-phase"` label instead of crashing -
  verified with a new test that reproduces exactly that condition.
- Promoted to `established`: manifest, docs, build-test/CI and this
  project's own real functional gap (above) all verified locally.
