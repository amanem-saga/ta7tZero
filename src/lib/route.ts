import { Company } from './types';

export interface RouteStep {
  company: Company;
  index: number;
  distanceFromPrev: number;
  cumulativeDist: number;
}

function haversine(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function optimizeRoute(companies: Company[], startLat: number, startLng: number): RouteStep[] {
  if (companies.length === 0) return [];
  if (companies.length === 1) {
    const d = haversine(startLat, startLng, companies[0].lat, companies[0].lng);
    return [{ company: companies[0], index: 0, distanceFromPrev: d, cumulativeDist: d }];
  }

  const n = companies.length;
  const visited = new Set<number>();
  const order: number[] = [];
  let curLat = startLat, curLng = startLng;

  for (let i = 0; i < n; i++) {
    let bestIdx = -1, bestDist = Infinity;
    for (let j = 0; j < n; j++) {
      if (visited.has(j)) continue;
      const d = haversine(curLat, curLng, companies[j].lat, companies[j].lng);
      if (d < bestDist) { bestDist = d; bestIdx = j; }
    }
    visited.add(bestIdx);
    order.push(bestIdx);
    curLat = companies[bestIdx].lat;
    curLng = companies[bestIdx].lng;
  }

  // 2-opt
  let improved = true, iters = 0;
  while (improved && iters < 30) {
    improved = false; iters++;
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 2; j < n; j++) {
        const a = order[i], b = order[i + 1], c = order[j];
        const d = order[(j + 1) % n];
        const pLat = i === 0 ? startLat : companies[order[i - 1]].lat;
        const pLng = i === 0 ? startLng : companies[order[i - 1]].lng;
        const d1 = haversine(pLat, pLng, companies[a].lat, companies[a].lng) +
          haversine(companies[c].lat, companies[c].lng, companies[d].lat, companies[d].lng);
        const d2 = haversine(pLat, pLng, companies[c].lat, companies[c].lng) +
          haversine(companies[a].lat, companies[a].lng, companies[d].lat, companies[d].lng);
        if (d2 < d1 - 1) {
          order.splice(i, j + 1 - i, ...order.slice(i, j + 1).reverse());
          improved = true;
        }
      }
    }
  }

  let cumDist = 0, prevLat = startLat, prevLng = startLng;
  return order.map((idx, i) => {
    const c = companies[idx];
    const dist = haversine(prevLat, prevLng, c.lat, c.lng);
    cumDist += dist;
    prevLat = c.lat; prevLng = c.lng;
    return { company: c, index: i, distanceFromPrev: dist, cumulativeDist: cumDist };
  });
}

export function formatDistance(m: number): string {
  if (m < 1000) return `${Math.round(m)}m`;
  return `${(m / 1000).toFixed(1)}km`;
}

export function formatDuration(m: number): string {
  const min = (m / 1000) / 30 * 60;
  if (min < 60) return `~${Math.max(1, Math.round(min))}min`;
  return `~${Math.round(min / 60 * 10) / 10}h`;
}

export function getGoogleMapsUrl(lat: number, lng: number, name: string, address?: string | null): string {
  // Use address for better Google Maps results when coords may be imprecise
  const q = address ? `${encodeURIComponent(address)} Meknes Morocco` : `${lat},${lng}`;
  return `https://www.google.com/maps/dir/?api=1&destination=${q}&destination_place_id=${encodeURIComponent(name)}`;
}

export function getOSRMRouteUrl(coords: [number, number][]): string {
  if (coords.length < 2) return '';
  return `https://router.project-osrm.org/route/v1/driving/${coords.map(c => `${c[0]},${c[1]}`).join(';')}?overview=full&geometries=geojson`;
}