# Checking the shared documentation

Pourpoint owns `mkdocs.yml`, the docs dependency group and `scripts/build_docs.py`.
The HFX `Documentation` workflow checks the proposed HFX revision with Pourpoint
main, using `--proposed-hfx`. It never advances Pourpoint's exact HFX pin or
publishes a site. Release assembly belongs to Pourpoint alone.

From a Pourpoint checkout with the shared build tooling, run:

```bash
uv run --frozen --group docs python scripts/build_docs.py --hfx-source /absolute/path/to/hfx --proposed-hfx
```

Only `docs/site/` is assembled into the reader-facing HFX section. Production
provenance under `scripts/provenance/` and this build note are not site sources.

The workflow uses `POURPOINT_DOCS_READ_KEY`, a read-only deploy key on the private
Pourpoint repository. Checkout does not persist credentials. The key is provisioned
as a repository Actions secret; no account-wide CLI token is used. The companion
Pourpoint build tooling must be merged to main before this remote check can pass.
