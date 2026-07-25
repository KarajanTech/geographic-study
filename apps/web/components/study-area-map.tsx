import type { BoundsWGS84, CandidateSite, GeoJSONGeometry } from "@sentinel/shared-schemas";

/**
 * Schematic viewer for a study area, its terrain preview and candidate sites.
 *
 * Every input is already in EPSG:4326 and was computed by the backend. This
 * component only plots them: it applies a cos(latitude) correction so the
 * shape is not stretched, and nothing else. It is a picture, not a measurement
 * — every figure on the page comes from the API.
 *
 * The interactive basemap arrives with the Phase 5 interface.
 */

interface ViewshedOverlay {
  id: string;
  url: string;
  bounds: BoundsWGS84;
}

interface StudyAreaMapProps {
  area: GeoJSONGeometry;
  previewUrl?: string | null;
  previewBounds?: BoundsWGS84 | null;
  candidates?: CandidateSite[];
  viewshedOverlays?: ViewshedOverlay[];
  height?: number;
}

type Ring = number[][];

function ringsOf(area: GeoJSONGeometry): Ring[] {
  // Polygon: [ring][point][xy]. MultiPolygon: [polygon][ring][point][xy].
  const coordinates = area.coordinates as unknown[];
  if (area.type === "Polygon") {
    return coordinates as Ring[];
  }
  return (coordinates as Ring[][]).flat();
}

interface Extent {
  west: number;
  south: number;
  east: number;
  north: number;
}

function extentOf(rings: Ring[], preview?: BoundsWGS84 | null): Extent {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  for (const ring of rings) {
    for (const point of ring) {
      const [x, y] = point;
      if (x === undefined || y === undefined) continue;
      west = Math.min(west, x);
      east = Math.max(east, x);
      south = Math.min(south, y);
      north = Math.max(north, y);
    }
  }
  if (preview) {
    west = Math.min(west, preview.west);
    east = Math.max(east, preview.east);
    south = Math.min(south, preview.south);
    north = Math.max(north, preview.north);
  }
  return { west, south, east, north };
}

export function StudyAreaMap({
  area,
  previewUrl,
  previewBounds,
  candidates = [],
  viewshedOverlays = [],
  height = 420,
}: StudyAreaMapProps): React.ReactElement {
  const rings = ringsOf(area);
  const extent = extentOf(rings, previewBounds);

  if (!Number.isFinite(extent.west) || extent.east <= extent.west) {
    return <p className="subtitle">No geometry to display.</p>;
  }

  // Equirectangular with a latitude correction, so a square on the ground
  // looks square on screen.
  const midLatitude = (extent.north + extent.south) / 2;
  const xScale = Math.cos((midLatitude * Math.PI) / 180);

  const pad = (extent.east - extent.west) * 0.04;
  const minX = (extent.west - pad) * xScale;
  const maxX = (extent.east + pad) * xScale;
  const minY = -(extent.north + pad);
  const maxY = -(extent.south - pad);
  const viewBox = `${minX} ${minY} ${maxX - minX} ${maxY - minY}`;

  const toPath = (ring: Ring): string =>
    ring
      .map((point, index) => {
        const [x, y] = point;
        if (x === undefined || y === undefined) return "";
        return `${index === 0 ? "M" : "L"}${x * xScale} ${-y}`;
      })
      .join(" ") + " Z";

  // Scaled to the geography so a dot stays a sensible size at any zoom level.
  const dotRadius = (extent.east - extent.west) * xScale * 0.006;

  return (
    <figure className="map" style={{ height }}>
      <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Study area">
        {previewUrl && previewBounds ? (
          <image
            href={previewUrl}
            x={previewBounds.west * xScale}
            y={-previewBounds.north}
            width={(previewBounds.east - previewBounds.west) * xScale}
            height={previewBounds.north - previewBounds.south}
            preserveAspectRatio="none"
            opacity={0.95}
          />
        ) : null}
        {viewshedOverlays.map((overlay) => (
          <image
            key={overlay.id}
            href={overlay.url}
            x={overlay.bounds.west * xScale}
            y={-overlay.bounds.north}
            width={(overlay.bounds.east - overlay.bounds.west) * xScale}
            height={overlay.bounds.north - overlay.bounds.south}
            preserveAspectRatio="none"
          />
        ))}
        {rings.map((ring, index) => (
          <path
            key={index}
            d={toPath(ring)}
            className="study-area-outline"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {candidates.map((candidate) => {
          const [lon, lat] = candidate.location.coordinates;
          if (lon === undefined || lat === undefined) return null;
          return (
            <circle
              key={candidate.id}
              cx={lon * xScale}
              cy={-lat}
              r={dotRadius}
              className={
                candidate.is_mandatory ? "candidate-dot candidate-dot-mandatory" : "candidate-dot"
              }
            />
          );
        })}
      </svg>
      <figcaption>
        Study area outline over the hillshaded surface
        {candidates.length > 0 ? `, with ${candidates.length} candidate sites` : ""}. Schematic
        projection, EPSG:4326.
      </figcaption>
    </figure>
  );
}
