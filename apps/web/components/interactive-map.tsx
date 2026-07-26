"use client";

import L from "leaflet";
import "leaflet-draw";
import { useEffect, useRef } from "react";

import type { BoundsWGS84, CandidateSite, GeoJSONGeometry } from "@sentinel/shared-schemas";

/**
 * Real basemap for drawing a study area and for viewing analysis results.
 *
 * Every figure shown here (coordinates, elevation, coverage) comes from the
 * API; Leaflet only projects and draws it. In "draw" mode the user outlines
 * one polygon and `onAreaChange` receives it as EPSG:4326 GeoJSON — nothing
 * about the polygon's geometry is computed here beyond what Leaflet needs to
 * render it. Rebuilt from scratch when its data changes: pass a `key` from
 * the parent (e.g. the project id) rather than expecting live prop diffing.
 */

export interface ViewshedOverlay {
  id: string;
  url: string;
  bounds: BoundsWGS84;
}

interface InteractiveMapProps {
  mode: "draw" | "view";
  initialArea?: GeoJSONGeometry | null;
  onAreaChange?: (geometry: GeoJSONGeometry | null) => void;
  previewUrl?: string | null;
  previewBounds?: BoundsWGS84 | null;
  candidates?: CandidateSite[];
  viewshedOverlays?: ViewshedOverlay[];
  selectedCandidateIds?: Set<string>;
  height?: number;
}

const OSM_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function toLatLngBounds(bounds: BoundsWGS84): L.LatLngBounds {
  return L.latLngBounds([bounds.south, bounds.west], [bounds.north, bounds.east]);
}

export function InteractiveMap({
  mode,
  initialArea = null,
  onAreaChange,
  previewUrl = null,
  previewBounds = null,
  candidates = [],
  viewshedOverlays = [],
  selectedCandidateIds,
  height = 420,
}: InteractiveMapProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onAreaChangeRef = useRef(onAreaChange);

  useEffect(() => {
    onAreaChangeRef.current = onAreaChange;
  }, [onAreaChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const map = L.map(container, { attributionControl: true }).setView([40, -3], 5);
    L.tileLayer(OSM_TILE_URL, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(map);

    const boundsToFit: L.LatLngBounds[] = [];

    if (mode === "draw") {
      const drawnItems = new L.FeatureGroup();
      map.addLayer(drawnItems);

      if (initialArea) {
        const layer = L.geoJSON(initialArea as GeoJSON.GeoJsonObject);
        layer.eachLayer((l) => drawnItems.addLayer(l));
        boundsToFit.push(drawnItems.getBounds());
      }

      const drawControl = new L.Control.Draw({
        draw: {
          polygon: { allowIntersection: false, showArea: true },
          marker: false,
          circle: false,
          circlemarker: false,
          polyline: false,
          rectangle: false,
        },
        edit: { featureGroup: drawnItems, remove: true },
      });
      map.addControl(drawControl);

      const emitChange = (): void => {
        const layer = drawnItems.getLayers()[0];
        if (!layer) {
          onAreaChangeRef.current?.(null);
          return;
        }
        const geojson = (layer as L.Polygon).toGeoJSON();
        onAreaChangeRef.current?.(geojson.geometry as unknown as GeoJSONGeometry);
      };

      map.on(L.Draw.Event.CREATED, (event: L.LeafletEvent) => {
        drawnItems.clearLayers(); // one study area at a time
        drawnItems.addLayer((event as L.DrawEvents.Created).layer);
        emitChange();
      });
      map.on(L.Draw.Event.EDITED, emitChange);
      map.on(L.Draw.Event.DELETED, emitChange);
    } else if (initialArea) {
      const layer = L.geoJSON(initialArea as GeoJSON.GeoJsonObject, {
        style: { color: "#3fb950", weight: 2, fillOpacity: 0.12 },
      }).addTo(map);
      boundsToFit.push(layer.getBounds());
    }

    if (previewUrl && previewBounds) {
      L.imageOverlay(previewUrl, toLatLngBounds(previewBounds), { opacity: 0.95 }).addTo(map);
      boundsToFit.push(toLatLngBounds(previewBounds));
    }

    for (const overlay of viewshedOverlays) {
      L.imageOverlay(overlay.url, toLatLngBounds(overlay.bounds)).addTo(map);
    }

    for (const candidate of candidates) {
      const [lon, lat] = candidate.location.coordinates;
      if (lon === undefined || lat === undefined) continue;
      const isSelected = selectedCandidateIds?.has(candidate.id) ?? false;
      const marker = L.circleMarker([lat, lon], {
        radius: isSelected ? 7 : candidate.is_mandatory ? 5 : 4,
        color: isSelected ? "#ffffff" : "#0e1116",
        weight: isSelected ? 2 : 1,
        fillColor: isSelected ? "#58a6ff" : candidate.is_mandatory ? "#f85149" : "#d29922",
        fillOpacity: 0.9,
      }).addTo(map);
      marker.bindPopup(
        `${lon.toFixed(5)}°, ${lat.toFixed(5)}° · ${candidate.elevation_m.toFixed(1)} m`,
      );
    }

    if (boundsToFit.length > 0) {
      const combined = boundsToFit.reduce((acc, b) => acc.extend(b));
      map.fitBounds(combined, { padding: [20, 20] });
    }

    return () => {
      map.remove();
    };
    // Rebuilt on mount only; the parent remounts this component (via `key`)
    // when the underlying project, candidates or solution change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} style={{ height }} className="interactive-map" />;
}
