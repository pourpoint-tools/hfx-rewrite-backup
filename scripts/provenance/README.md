# Retained production provenance

The GRIT producer and its independent verification tests consume
`grit-original-inventory.json` and `grit-raster-delivery.json` as pinned source
identities and raster declarations. These records are retained production inputs,
not reader-facing documentation or new validation results. Do not replace their
identities with hashes from an untrusted download.

`NOTICE` and `CITATION.txt` preserve the source attribution formerly carried by
the raster experiment. GRIT data is CC BY-NC 4.0; repository code is MIT.
Historical build, delivery and experiment records remain in Git history.
