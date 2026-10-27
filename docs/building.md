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

The workflow requires `POURPOINT_DOCS_READ_TOKEN`, restricted to `contents:read`
on the private Pourpoint repository. Checkout does not persist credentials.
Credential provisioning is currently blocked: deploy keys are disabled by
organization policy, and an alternative credential has not been configured.
The workflow therefore fails explicitly until authorized access is supplied;
local strict-build success is not evidence of working cross-repository CI.
No account-wide CLI token should be copied into this secret.
