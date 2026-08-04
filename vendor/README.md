# Vendored dependencies

## sentree

Vendored copy of the `sentree` package (MIT licensed, see `sentree/LICENSE`),
copied from `src/sentree` in the private repo
`github.com/TheoryVentures/sentree` at commit
`d3ff00489bf2ec1adc3f2ef1d59961314bb57334`.

To update, re-copy `src/sentree` from the sentree checkout over
`vendor/sentree` (excluding `__pycache__`), keep the LICENSE file, and record
the new commit hash here. The package uses absolute internal imports and is
shipped as a top-level `sentree` package inside the sixwords wheel, so no
import rewriting is needed.
