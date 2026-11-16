# Ash LiveKit Server dependency distribution

This repository builds and verifies LiveKit Server inputs for all six Ash desktop
and server targets. It does not fork LiveKit business logic or publish Ash products.

`upstream-lock.json` pins upstream source and official Windows/Linux binary hashes.
`build-inputs.json` pins the Go toolchain and distribution revision. The producer,
verified downloader, archive preparation and release verification live here. No
Ash checkout or Ash build scripts are required. Each native result records hashes
of the complete producer recipe; aggregation rejects mixed recipes. macOS builds use the pinned Go toolchain
and upstream source; Windows/Linux import the verified official executables.
Every native job checks the server version before packaging the executable and
upstream notices. Release aggregation verifies all six archives before generating
the consumer lock. Tags use `livekit-v<version>-ash.<revision>`.
`releaseRevision` permits a new distribution of the same upstream version without
replacing an existing release. `goVersion` pins the exact patch version; native
macOS jobs verify it and record it in the build provenance.

Recipe changes and pull requests validate without publishing; fixed recipes have no scheduled rebuild. A dependency tag
publishes immutable archives, provenance, checksums and `runtime-lock.json`.
Ash adopts that exact lock; ordinary Ash CI does not compile the Go server.
LiveKit client/server integration tests stay in the Ash repository.
