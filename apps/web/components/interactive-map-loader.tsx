"use client";

import dynamic from "next/dynamic";

/**
 * Leaflet touches `window` as soon as its module is evaluated, which crashes
 * Next.js's server-side prerender pass. Loading it through `next/dynamic`
 * with `ssr: false` keeps that import out of the server bundle entirely —
 * this is the only place `interactive-map.tsx` may be imported from.
 */
export const InteractiveMap = dynamic(
  () => import("./interactive-map").then((mod) => mod.InteractiveMap),
  { ssr: false },
);
