# DEM sources

No elevation dataset is committed to this repository: licences differ per
provider and raw data does not belong in git. Download what you need into
`data/raw`, which is git-ignored and treated as immutable.

```bash
uv run --project apps/api python scripts/fetch_dem.py <url> --expected-sha256 <hex>
```

The script refuses to overwrite an existing file without `--force`, downloads to
a temporary file first, and verifies the checksum before moving it into place.

## Public providers

| Source                                    | Coverage      | Typical resolution | Notes                                  |
| ----------------------------------------- | ------------- | ------------------ | -------------------------------------- |
| Centro Nacional de Información Geográfica | Spain         | 2 m / 5 m / 25 m   | MDT05 and MDT25 are the usual choices. |
| Copernicus DEM (GLO-30)                   | Global        | 30 m               | Free, registration may be required.    |
| NASADEM / SRTM                            | Global (±60°) | 30 m               | Older, but easy to obtain.             |
| OpenTopography                            | Varies        | Varies             | API key required for some datasets.    |

Verify licence and attribution before using any dataset in a commercial study.

## What the pipeline needs

Phase 1 validation will reject a GeoTIFF that lacks any of:

- a defined CRS;
- a sane resolution;
- a declared nodata value;
- an intersection with the study area.

A DEM in a geographic CRS (EPSG:4326) is accepted as input but is reprojected to
a projected metric CRS before any calculation. Distances are never computed in
degrees.

## Synthetic alternative

For tests and demos, generate terrain instead of downloading it:

```bash
make sample-dem
```

The output carries `source=synthetic` in its GeoTIFF tags together with the full
generation spec, so it can always be distinguished from real data. It is never
a substitute for a real DEM in a study.
