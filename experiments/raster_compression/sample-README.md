# Temporary GRIT compression samples

Derived from GRIT raster datasets, Wortmann et al. (2025), DOI
10.5281/zenodo.15715535. CC BY-NC 4.0; see NOTICE and CITATION.txt.
Source: https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/
Native 30 m EPSG:8857 cropped patches; no resampling or hydrology changes.
Direction: GRASS uint8/nodata255, DEFLATE/no predictor unchanged.
Accumulation: width-partitioned drainage area, km² float32/nodataNaN.
Encoding comparison only: DEFLATE 6/predictor1, DEFLATE 6/predictor3,
ZSTD 9/predictor3; 512×512 tiles, no overviews. Objects are temporary.
