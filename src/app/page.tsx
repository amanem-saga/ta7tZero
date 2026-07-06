'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { Company, CompanyData, TabView } from '@/lib/types';
import { optimizeRoute, formatDistance, formatDuration, getGoogleMapsUrl, getOSRMRouteUrl, RouteStep } from '@/lib/route';

const MEKNES: [number, number] = [-5.5407, 33.8730]; // [lng, lat] for Mapbox
const SECTOR_COLORS: Record<string, string> = {
  'Commerce & Négoce': '#ef4444',
  'Bâtiment & Travaux Publics': '#f59e0b',
  'Services aux entreprises': '#3b82f6',
  'Restauration & Hôtellerie': '#f97316',
  'Industrie & Fabrication': '#8b5cf6',
  'Éducation & Formation': '#10b981',
  'Agriculture & Élevage': '#22c55e',
  'Transport & Logistique': '#f97316',
  'Technologie & Digital': '#06b6d4',
  'Automobile': '#e11d48',
  'Textile & Habillement': '#ec4899',
  'Santé & Pharmacie': '#14b8a6',
  'Agroalimentaire': '#84cc16',
};
const getColor = (s: string | null) => SECTOR_COLORS[s || ''] || '#6b7280';

export default function Home() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const routeSourceRef = useRef<string | null>(null);

  const [data, setData] = useState<CompanyData | null>(null);
  const [token, setToken] = useState('');
  const [mapLoaded, setMapLoaded] = useState(false);

  // Read token from server-injected global
  useEffect(() => {
    const t = (window as unknown as { __MAPBOX_TOKEN__?: string }).__MAPBOX_TOKEN__;
    if (t) setToken(t);
  }, []);
  const [selectedSectors, setSelectedSectors] = useState<Set<string>>(new Set());
  const [selectedSlugs, setSelectedSlugs] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try { return new Set(JSON.parse(localStorage.getItem('selected') || '[]')); } catch { return new Set(); }
  });
  const [visitedSlugs, setVisitedSlugs] = useState<Set<string>>(() => {
    if (typeof window === 'undefined') return new Set();
    try { return new Set(JSON.parse(localStorage.getItem('visited') || '[]')); } catch { return new Set(); }
  });
  const [geocodedCoords, setGeocodedCoords] = useState<Record<string, {lat:number;lng:number}>>(() => {
    if (typeof window === 'undefined') return {};
    try { return JSON.parse(localStorage.getItem('geocoded') || '{}'); } catch { return {}; }
  });
  const [route, setRoute] = useState<RouteStep[] | null>(null);
  const [routeIdx, setRouteIdx] = useState(0);
  const [activeCompany, setActiveCompany] = useState<Company | null>(null);
  const [topExpanded, setTopExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<TabView>('map');
  const [search, setSearch] = useState('');
  const [routeLoading, setRouteLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [geocoding, setGeocoding] = useState(false);
  const [geoProgress, setGeoProgress] = useState({ done: 0, total: 0 });

  // Load data
  useEffect(() => {
    fetch('/companies.json').then(r => r.json()).then((d: CompanyData) => setData(d));
  }, []);

  // Persist state
  useEffect(() => { localStorage.setItem('visited', JSON.stringify([...visitedSlugs])); }, [visitedSlugs]);
  useEffect(() => { localStorage.setItem('selected', JSON.stringify([...selectedSlugs])); }, [selectedSlugs]);
  useEffect(() => { localStorage.setItem('geocoded', JSON.stringify(geocodedCoords)); }, [geocodedCoords]);

  // Get effective coords (geocoded override or default)
  const getCoords = useCallback((c: Company): [number, number] => {
    if (geocodedCoords[c.slug]) return [geocodedCoords[c.slug].lng, geocodedCoords[c.slug].lat];
    if (c.has_real_coords) return [c.lng, c.lat];
    return [c.lng, c.lat]; // default fallback
  }, [geocodedCoords]);

  // Filtered companies
  const filtered = data ? data.companies.filter(c => {
    if (selectedSectors.size > 0 && !selectedSectors.has(c.sector || '')) return false;
    if (search) {
      const q = search.toLowerCase();
      return c.name.toLowerCase().includes(q) || (c.address || '').toLowerCase().includes(q) || (c.sector || '').toLowerCase().includes(q);
    }
    return true;
  }) : [];

  // Companies with mappable coords (real or geocoded)
  const mappable = filtered.filter(c => c.has_real_coords || geocodedCoords[c.slug]);

  // Init Mapbox map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current || !token) return;
    mapboxgl.accessToken = token;
    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: MEKNES,
      zoom: 12,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'bottom-left');
    map.on('load', () => setMapLoaded(true));
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [token]);

  // Update markers
  useEffect(() => {
    if (!mapLoaded || !mapRef.current || !data) return;
    const map = mapRef.current;

    // Clear old markers
    markersRef.current.forEach(m => m.remove());
    markersRef.current = [];

    // Add markers for mappable companies
    mappable.forEach(company => {
      const [lng, lat] = getCoords(company);
      const isSelected = selectedSlugs.has(company.slug);
      const isVisited = visitedSlugs.has(company.slug);
      const color = getColor(company.sector);
      const size = isSelected ? 18 : isVisited ? 10 : 12;
      const bgColor = isVisited ? '#22c55e' : isSelected ? '#ef4444' : color;

      const el = document.createElement('div');
      el.style.cssText = `width:${size}px;height:${size}px;border-radius:50%;background:${bgColor};border:2px solid rgba(255,255,255,0.9);box-shadow:0 2px 8px rgba(0,0,0,0.4);cursor:pointer;transition:transform 0.15s;`;

      const marker = new mapboxgl.Marker({ element: el })
        .setLngLat([lng, lat])
        .addTo(map);

      el.addEventListener('click', () => {
        setActiveCompany(company);
        setTopExpanded(false);
        map.flyTo({ center: [lng, lat], zoom: 16, duration: 600 });
      });

      markersRef.current.push(marker);
    });
  }, [mapLoaded, mappable, selectedSlugs, visitedSlugs, data, geocodedCoords]);

  // Fit bounds when first data loads
  useEffect(() => {
    if (!mapLoaded || !mapRef.current || !mappable.length) return;
    const bounds = new mapboxgl.LngLatBounds();
    mappable.forEach(c => { const [lng, lat] = getCoords(c); bounds.extend([lng, lat]); });
    mapRef.current.fitBounds(bounds, { padding: { top: 80, bottom: 200, left: 20, right: 20 }, duration: 800 });
  }, [mapLoaded, data, geocodedCoords]);

  // Draw route on map
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;

    if (routeSourceRef.current) {
      if (map.getSource(routeSourceRef.current)) map.removeSource(routeSourceRef.current);
      if (map.getLayer(routeSourceRef.current)) map.removeLayer(routeSourceRef.current);
      routeSourceRef.current = null;
    }

    if (!route || route.length < 2) return;

    const coords: [number, number][] = route.map(s => {
      const [lng, lat] = getCoords(s.company);
      return [lng, lat];
    });

    const srcId = 'route-line';
    routeSourceRef.current = srcId;

    map.addSource(srcId, {
      type: 'geojson',
      data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } },
    });
    map.addLayer({
      id: srcId, type: 'line', source: srcId,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': '#3b82f6', 'line-width': 4, 'line-opacity': 0.8 },
    });

    // Fit route bounds
    const bounds = new mapboxgl.LngLatBounds();
    coords.forEach(c => bounds.extend(c));
    map.fitBounds(bounds, { padding: { top: 80, bottom: 250, left: 20, right: 20 } });

    // Try OSRM for real road path
    getOSRMRouteUrl(coords).then(url => {
      if (!url) return;
      fetch(url).then(r => r.json()).then(geojson => {
        if (geojson.routes?.[0]?.geometry && map.getSource(srcId)) {
          (map.getSource(srcId) as mapboxgl.GeoJSONSource).setData(geojson.routes[0].geometry);
        }
      }).catch(() => {});
    });
  }, [route, mapLoaded]);

  // Geocoding function — calls Mapbox API directly from client
  const startGeocoding = async () => {
    if (!data || geocoding || !token) return;
    setGeocoding(true);
    const toGeocode = data.companies.filter(c => !c.has_real_coords && !geocodedCoords[c.slug] && c.address);
    setGeoProgress({ done: 0, total: toGeocode.length });

    const BATCH = 5;
    for (let i = 0; i < toGeocode.length; i += BATCH) {
      const batch = toGeocode.slice(i, i + BATCH);
      const results: Record<string, { lat: number; lng: number } | null> = {};
      await Promise.all(batch.map(async (c) => {
        try {
          const q = `${c.address}${c.city ? `, ${c.city}` : ''}, Morocco`;
          const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(q)}.json?access_token=${token}&country=ma&limit=1`;
          const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
          const data = await resp.json();
          if (data.features?.[0]?.center) {
            results[c.slug] = { lng: data.features[0].center[0], lat: data.features[0].center[1] };
          } else { results[c.slug] = null; }
        } catch { results[c.slug] = null; }
      }));
      setGeocodedCoords(prev => {
        const next = { ...prev };
        for (const [slug, coords] of Object.entries(results)) { if (coords) next[slug] = coords; }
        return next;
      });
      setGeoProgress({ done: Math.min(i + BATCH, toGeocode.length), total: toGeocode.length });
      if (i + BATCH < toGeocode.length) await new Promise(r => setTimeout(r, 350));
    }
    setGeocoding(false);
  };

  const toggleSector = (s: string) => setSelectedSectors(p => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const toggleSelect = (slug: string) => { setSelectedSlugs(p => { const n = new Set(p); n.has(slug) ? n.delete(slug) : n.add(slug); return n; }); setRoute(null); };
  const selectAll = () => { setSelectedSlugs(new Set(mappable.map(c => c.slug))); setRoute(null); };
  const deselectAll = () => { setSelectedSlugs(new Set()); setRoute(null); };
  const markVisited = (slug: string) => setVisitedSlugs(p => new Set([...p, slug]));
  const markUnvisited = (slug: string) => setVisitedSlugs(p => { const n = new Set(p); n.delete(slug); return n; });

  const doOptimize = useCallback(() => {
    if (selectedSlugs.size < 2) return;
    setRouteLoading(true);
    const sel = mappable.filter(c => selectedSlugs.has(c.slug));
    setTimeout(() => {
      const optimized = optimizeRoute(sel, 33.8730, -5.5407);
      setRoute(optimized);
      setRouteIdx(0);
      setRouteLoading(false);
      setActiveTab('map');
      if (optimized.length > 0) {
        const [lng, lat] = getCoords(optimized[0].company);
        setActiveCompany(optimized[0].company);
        mapRef.current?.flyTo({ center: [lng, lat], zoom: 16, duration: 600 });
      }
    }, 50);
  }, [selectedSlugs, mappable, geocodedCoords]);

  const goNext = () => { if (!route || routeIdx >= route.length - 1) return; const i = routeIdx + 1; setRouteIdx(i); const c = route[i].company; setActiveCompany(c); const [lng, lat] = getCoords(c); mapRef.current?.flyTo({ center: [lng, lat], zoom: 17, duration: 400 }); };
  const goPrev = () => { if (!route || routeIdx <= 0) return; const i = routeIdx - 1; setRouteIdx(i); const c = route[i].company; setActiveCompany(c); const [lng, lat] = getCoords(c); mapRef.current?.flyTo({ center: [lng, lat], zoom: 17, duration: 400 }); };
  const navigateTo = (c: Company) => window.open(getGoogleMapsUrl(c.lat, c.lng, c.name, c.address), '_blank');

  if (!data) return (
    <div className="h-dvh flex items-center justify-center bg-slate-950">
      <div className="text-center"><div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-3" style={{animation:'spin-slow 1s linear infinite'}}/><p className="text-slate-400 text-sm">Loading companies...</p></div>
    </div>
  );

  const cur = route ? route[routeIdx]?.company : activeCompany;
  const needGeo = data.stats.default_coords - Object.keys(geocodedCoords).length;
  const mapSelected = mappable.filter(c => selectedSlugs.has(c.slug));

  return (
    <div className="flex flex-col bg-slate-950 overflow-hidden" style={{ height: '100dvh', width: '100vw' }}>
      {/* MAP */}
      <div className="flex-1 relative">
        <div ref={mapContainer} className="absolute inset-0" />

        {/* SEARCH BAR (when no company active) */}
        {(!activeCompany && !route) && (
          <div className="absolute top-0 left-0 right-0 z-10 p-3" style={{animation:'fade-in 0.2s'}}>
            <div className="flex items-center gap-2 bg-slate-900/90 backdrop-blur-xl rounded-2xl px-4 h-12 border border-slate-700/50">
              <svg className="w-5 h-5 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
              <input type="text" placeholder="Search companies, sectors, addresses..." className="flex-1 bg-transparent text-sm text-white placeholder-slate-400 outline-none min-w-0" value={search} onChange={e => setSearch(e.target.value)} />
              {search ? <button onClick={() => setSearch('')} className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center"><svg className="w-3 h-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg></button>
              : <button onClick={() => setShowFilters(!showFilters)} className={`w-8 h-8 rounded-lg flex items-center justify-center ${showFilters ? 'bg-blue-600' : 'bg-slate-800'}`}><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg></button>}
            </div>

            {/* GEOCODE BANNER */}
            {needGeo > 0 && (
              <div className="mt-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-amber-400">{needGeo} companies need geocoding</p>
                    <p className="text-[10px] text-amber-500/70">Addresses exist but map coordinates are missing</p>
                  </div>
                  <button onClick={startGeocoding} disabled={geocoding}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-amber-500 text-black disabled:opacity-50 active:scale-95 transition-transform">
                    {geocoding ? `${Math.round(geoProgress.done/geoProgress.total*100)}%` : 'Geocode All'}
                  </button>
                </div>
                {geocoding && <div className="mt-2 h-1 bg-slate-800 rounded-full overflow-hidden"><div className="h-full bg-amber-500 rounded-full transition-all" style={{width:`${(geoProgress.done/geoProgress.total)*100}%`}}/></div>}
              </div>
            )}

            {/* FILTER CHIPS */}
            {showFilters && (
              <div className="mt-2 p-3 bg-slate-900/90 backdrop-blur-xl rounded-2xl border border-slate-700/50" style={{animation:'fade-in 0.15s'}}>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Sectors</p>
                  <div className="flex gap-1">
                    <button onClick={() => setSelectedSectors(new Set(data.sectors))} className="text-[10px] text-blue-400 font-medium px-2 py-0.5">All</button>
                    <button onClick={() => setSelectedSectors(new Set())} className="text-[10px] text-slate-400 font-medium px-2 py-0.5">None</button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {data.sectors.map(s => (
                    <button key={s} onClick={() => toggleSector(s)} className="text-[11px] px-3 py-1.5 rounded-full border transition-all active:scale-95"
                      style={{ borderColor: selectedSectors.has(s) ? getColor(s) : '#334155', background: selectedSectors.has(s) ? getColor(s)+'20' : 'transparent', color: selectedSectors.has(s) ? getColor(s) : '#64748b', fontWeight: selectedSectors.has(s) ? 600 : 400 }}>
                      {s}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-slate-500 mt-2">{filtered.length} of {data.companies.length} companies · {mappable.length} on map</p>
              </div>
            )}
          </div>
        )}

        {/* TOP SHEET — Company Info */}
        {cur && (
          <div className="absolute top-0 left-0 right-0 z-10" style={{animation:'slide-up 0.3s ease'}}>
            <div className="flex justify-center pt-2 pb-1 cursor-pointer" onClick={() => setTopExpanded(!topExpanded)}>
              <div className="w-10 h-1 rounded-full bg-slate-600" />
            </div>
            <div className="mx-2 rounded-2xl overflow-hidden border border-slate-700/50" style={{ maxHeight: topExpanded ? '70dvh' : 'auto', background: 'rgba(15,23,42,0.95)', backdropFilter: 'blur(20px)', transition: 'max-height 0.35s cubic-bezier(0.32,0.72,0,1)' }}>
              {/* Header */}
              <div className="flex items-center gap-3 p-3 cursor-pointer" onClick={() => setTopExpanded(!topExpanded)}>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:getColor(cur.sector)+'20'}}>
                  <svg className="w-5 h-5" style={{color:getColor(cur.sector)}} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white truncate">{cur.name}</p>
                  <p className="text-xs text-slate-400 truncate">{cur.address || cur.sector || ''}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {route && <span className="text-xs font-bold text-blue-400 bg-blue-500/20 px-2 py-0.5 rounded-md">{routeIdx+1}/{route.length}</span>}
                  {topExpanded ? <svg className="w-5 h-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/></svg> : <svg className="w-5 h-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7"/></svg>}
                </div>
              </div>

              {/* Expanded details */}
              {topExpanded && (
                <div className="px-4 pb-4 space-y-3" style={{animation:'fade-in 0.2s'}}>
                  <div className="h-px bg-slate-800" />
                  <div className="flex flex-wrap gap-1.5">
                    {cur.sector && <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium" style={{borderColor:getColor(cur.sector),color:getColor(cur.sector)}}>{cur.sector}</span>}
                    {cur.category && <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">{cur.category}</span>}
                    {cur.status && <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">{cur.status}</span>}
                    {!cur.has_real_coords && !geocodedCoords[cur.slug] && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">⚠ No exact coords</span>}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {cur.ice && <div className="bg-slate-800/50 rounded-xl p-2.5"><p className="text-[10px] text-slate-500 uppercase font-medium">ICE</p><p className="text-xs font-mono text-slate-300 mt-0.5">{cur.ice}</p></div>}
                    {cur.rc && <div className="bg-slate-800/50 rounded-xl p-2.5"><p className="text-[10px] text-slate-500 uppercase font-medium">Reg. Commerce</p><p className="text-xs font-mono text-slate-300 mt-0.5">{cur.rc}</p></div>}
                    {cur.employees && <div className="bg-slate-800/50 rounded-xl p-2.5"><p className="text-[10px] text-slate-500 uppercase font-medium">Effectif</p><p className="text-xs text-slate-300 mt-0.5">{cur.employees}</p></div>}
                    {cur.date_creation && <div className="bg-slate-800/50 rounded-xl p-2.5"><p className="text-[10px] text-slate-500 uppercase font-medium">Created</p><p className="text-xs text-slate-300 mt-0.5">{cur.date_creation}</p></div>}
                  </div>
                  {cur.description && <div><p className="text-[10px] text-slate-500 uppercase font-medium mb-1">Description</p><p className="text-xs text-slate-400 leading-relaxed">{cur.description}</p></div>}
                  {(cur.phone1 || cur.phone2) && <div className="flex gap-2 flex-wrap">{[cur.phone1, cur.phone2, cur.phone3].filter(Boolean).map((p,i) => <a key={i} href={`tel:${p}`} className="text-xs text-blue-400 underline">{p}</a>)}</div>}
                  {route && <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-3 flex justify-between"><div><p className="text-[10px] text-blue-400">From prev</p><p className="text-sm font-bold text-blue-300">{formatDistance(route[routeIdx].distanceFromPrev)} · {formatDuration(route[routeIdx].distanceFromPrev)}</p></div><div className="text-right"><p className="text-[10px] text-blue-400">Total</p><p className="text-sm font-bold text-blue-300">{formatDistance(route[routeIdx].cumulativeDist)}</p></div></div>}
                  <div className="flex gap-2">
                    <button onClick={() => navigateTo(cur)} className="flex-1 h-11 rounded-xl bg-green-600 active:bg-green-700 text-white text-sm font-semibold flex items-center justify-center gap-1.5"><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>Google Maps</button>
                    <button onClick={() => visitedSlugs.has(cur.slug) ? markUnvisited(cur.slug) : markVisited(cur.slug)} className={`h-11 w-11 rounded-xl flex items-center justify-center border ${visitedSlugs.has(cur.slug) ? 'bg-green-500/20 border-green-500/50 text-green-400' : 'bg-slate-800 border-slate-700 text-slate-400'}`}><svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7"/></svg></button>
                    <button onClick={() => toggleSelect(cur.slug)} className={`h-11 w-11 rounded-xl flex items-center justify-center border ${selectedSlugs.has(cur.slug) ? 'bg-blue-500/20 border-blue-500/50 text-blue-400' : 'bg-slate-800 border-slate-700 text-slate-400'}`}><svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/></svg></button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* GENERATE ROUTE FAB */}
        {selectedSlugs.size > 0 && !route && (
          <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-10" style={{animation:'slide-up 0.3s'}}>
            <div className="flex items-center gap-2 bg-slate-900/95 backdrop-blur-xl rounded-2xl shadow-2xl px-3 py-2.5 border border-slate-700/50">
              <div className="w-8 h-8 rounded-xl bg-blue-600 flex items-center justify-center"><span className="text-white text-xs font-bold">{selectedSlugs.size}</span></div>
              <button onClick={doOptimize} disabled={selectedSlugs.size < 2 || routeLoading}
                className="h-10 rounded-xl bg-blue-600 active:bg-blue-700 text-white text-sm font-semibold px-4 disabled:opacity-40 flex items-center gap-1.5">
                {routeLoading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full" style={{animation:'spin-slow 0.8s linear infinite'}}/> : <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>}
                Generate Route
              </button>
              <button onClick={deselectAll} className="w-8 h-8 rounded-xl bg-slate-800 flex items-center justify-center"><svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg></button>
            </div>
          </div>
        )}

        {/* ROUTE NAV BAR (Waze bottom bar) */}
        {route && route.length > 0 && (
          <div className="absolute bottom-20 left-2 right-2 z-10" style={{animation:'slide-up 0.3s'}}>
            <div className="bg-slate-900/95 backdrop-blur-xl rounded-2xl border border-slate-700/50 p-3 shadow-2xl">
              <div className="h-1 bg-slate-800 rounded-full mb-3 overflow-hidden"><div className="h-full bg-blue-500 rounded-full transition-all" style={{width:`${((routeIdx+1)/route.length)*100}%`}}/></div>
              <div className="flex items-center gap-2">
                <button onClick={goPrev} disabled={routeIdx<=0} className="w-12 h-12 rounded-xl bg-slate-800 flex items-center justify-center flex-shrink-0 disabled:opacity-30 active:scale-95 transition-transform"><svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/></svg></button>
                <button onClick={() => { setActiveCompany(route[routeIdx].company); setTopExpanded(!topExpanded); }} className="flex-1 min-w-0 text-left bg-slate-800 rounded-xl p-2.5 active:bg-slate-700 transition-colors">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0"><span className="text-white text-xs font-bold">{routeIdx+1}</span></div>
                    <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-white truncate">{route[routeIdx].company.name}</p><p className="text-[10px] text-slate-400 truncate">{route[routeIdx].company.address || route[routeIdx].company.sector}</p></div>
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 ml-9">
                    <span className="text-[10px] text-slate-500">+{formatDistance(route[routeIdx].distanceFromPrev)}</span>
                    <span className="text-[10px] text-slate-500">{formatDuration(route[routeIdx].distanceFromPrev)}</span>
                    <span className="text-[10px] text-blue-400">Total: {formatDistance(route[routeIdx].cumulativeDist)}</span>
                  </div>
                </button>
                <button onClick={goNext} disabled={routeIdx>=route.length-1} className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center flex-shrink-0 disabled:opacity-30 disabled:bg-slate-800 active:scale-95 transition-transform"><svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/></svg></button>
              </div>
              <div className="flex gap-2 mt-3">
                <button onClick={() => navigateTo(route[routeIdx].company)} className="flex-1 h-11 rounded-xl bg-green-600 active:bg-green-700 text-white text-sm font-semibold flex items-center justify-center gap-1.5"><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>Navigate</button>
                <button onClick={() => visitedSlugs.has(route[routeIdx].company.slug) ? markUnvisited(route[routeIdx].company.slug) : markVisited(route[routeIdx].company.slug)} className={`h-11 rounded-xl px-4 text-xs font-medium ${visitedSlugs.has(route[routeIdx].company.slug) ? 'bg-green-500/20 text-green-400' : 'bg-slate-800 text-slate-400'}`}>{visitedSlugs.has(route[routeIdx].company.slug) ? '✓ Done' : 'Mark'}</button>
                <button onClick={() => { setRoute(null); setRouteIdx(0); }} className="h-11 w-11 rounded-xl bg-slate-800 flex items-center justify-center text-red-400"><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg></button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* BOTTOM TAB BAR */}
      <div className="flex-shrink-0 bg-slate-900 border-t border-slate-800 z-20" style={{paddingBottom:'env(safe-area-inset-bottom,0px)'}}>
        <div className="flex items-center justify-around h-14">
          {(['map','list','route'] as TabView[]).map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} className={`flex flex-col items-center justify-center gap-0.5 w-16 h-full transition-colors ${activeTab===tab ? 'text-blue-400' : 'text-slate-500'}`}>
              {tab === 'map' && <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>}
              {tab === 'list' && <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>}
              {tab === 'route' && <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>}
              <span className="text-[10px] font-medium capitalize">{tab}</span>
              <div className={`w-5 h-0.5 rounded-full bg-blue-400 transition-transform ${activeTab===tab ? 'scale-x-100' : 'scale-x-0'}`} />
              {tab === 'route' && selectedSlugs.size > 0 && !route && <div className="absolute top-1.5 right-2 w-4 h-4 bg-red-500 rounded-full flex items-center justify-center"><span className="text-[8px] text-white font-bold">{selectedSlugs.size > 99 ? '99+' : selectedSlugs.size}</span></div>}
            </button>
          ))}
        </div>
      </div>

      {/* LIST VIEW OVERLAY */}
      {activeTab === 'list' && (
        <div className="absolute inset-0 z-30 bg-slate-950 flex flex-col" style={{paddingBottom:'calc(56px + env(safe-area-inset-bottom,0px))'}}>
          <div className="flex-shrink-0 px-4 pt-3 pb-2">
            <div className="flex items-center justify-between mb-2">
              <div><h2 className="text-lg font-bold text-white">Companies</h2><p className="text-xs text-slate-500">{filtered.length} results · {mappable.length} on map</p></div>
              <div className="flex gap-1.5"><button onClick={selectAll} className="text-xs text-blue-400 font-medium px-3 py-1.5 rounded-lg bg-blue-500/10">All</button><button onClick={deselectAll} className="text-xs text-slate-400 font-medium px-3 py-1.5 rounded-lg bg-slate-800">Clear</button></div>
            </div>
            <div className="flex items-center gap-2 bg-slate-900 rounded-xl px-3 h-10 border border-slate-800"><svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg><input type="text" placeholder="Search..." className="flex-1 bg-transparent text-sm text-white outline-none" value={search} onChange={e => setSearch(e.target.value)} /></div>
            <div className="flex gap-1.5 mt-2 overflow-x-auto mobile-scroll pb-1">
              <button onClick={() => setSelectedSectors(new Set())} className={`text-[10px] px-2.5 py-1 rounded-full border whitespace-nowrap flex-shrink-0 ${selectedSectors.size===0 ? 'bg-white text-slate-900 border-white' : 'border-slate-700 text-slate-500'}`}>All</button>
              {data.sectors.map(s => <button key={s} onClick={() => toggleSector(s)} className="text-[10px] px-2.5 py-1 rounded-full border whitespace-nowrap flex-shrink-0" style={selectedSectors.has(s) ? {borderColor:getColor(s),background:getColor(s)+'20',color:getColor(s),fontWeight:600} : {borderColor:'#334155',color:'#64748b'}}>{s}</button>)}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto mobile-scroll">
            {filtered.map(c => {
              const sel = selectedSlugs.has(c.slug), vis = visitedSlugs.has(c.slug), hasCoords = c.has_real_coords || geocodedCoords[c.slug];
              return (
                <div key={c.slug} onClick={() => { if(hasCoords){ setActiveCompany(c); setTopExpanded(false); setActiveTab('map'); const [lng,lat]=getCoords(c); mapRef.current?.flyTo({center:[lng,lat],zoom:17,duration:400}); } }}
                  className={`flex items-center gap-3 px-4 py-3 border-b border-slate-800/50 active:bg-slate-800/50 transition-colors ${vis?'opacity-50':''}`}>
                  <div className="w-1.5 h-10 rounded-full flex-shrink-0" style={{background:getColor(c.sector)}} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{c.name}</p>
                    <p className="text-xs text-slate-500 truncate">{c.address || c.sector || ''}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {c.sector && <span className="text-[10px] text-slate-600">{c.sector}</span>}
                      {!hasCoords && <span className="text-[10px] text-amber-500">⚠ no coords</span>}
                    </div>
                  </div>
                  {vis && <svg className="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7"/></svg>}
                  <button onClick={e => { e.stopPropagation(); toggleSelect(c.slug); }} className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs flex-shrink-0 ${sel ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-500'}`}>{sel ? '✓' : '+'}</button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ROUTE VIEW OVERLAY */}
      {activeTab === 'route' && (
        <div className="absolute inset-0 z-30 bg-slate-950 flex flex-col" style={{paddingBottom:'calc(56px + env(safe-area-inset-bottom,0px))'}}>
          <div className="flex-shrink-0 px-4 pt-3 pb-3 border-b border-slate-800">
            <div className="flex items-center justify-between">
              <div><h2 className="text-lg font-bold text-white">Route Plan</h2>
                {route ? <div className="flex items-center gap-2 mt-0.5"><span className="text-xs text-slate-400">{route.length} stops</span><span className="text-xs text-slate-600">·</span><span className="text-xs text-slate-400">{formatDistance(route[route.length-1].cumulativeDist)}</span><span className="text-xs text-slate-600">·</span><span className="text-xs text-slate-400">{formatDuration(route[route.length-1].cumulativeDist)}</span></div>
                : <p className="text-xs text-slate-500 mt-0.5">{mapSelected.length} mappable companies selected</p>}
              </div>
              {route && <button onClick={() => { setRoute(null); setRouteIdx(0); }} className="text-xs text-red-400 font-medium px-3 py-1.5 rounded-lg bg-red-500/10">Clear</button>}
            </div>
            {!route && mapSelected.length >= 2 && <button onClick={doOptimize} disabled={routeLoading} className="w-full mt-3 h-12 rounded-xl bg-blue-600 active:bg-blue-700 text-white font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-40">{routeLoading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full" style={{animation:'spin-slow 0.8s linear infinite'}}/> : <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/></svg>}Optimize Route for {mapSelected.length} Companies</button>}
            {!route && mapSelected.length < 2 && <div className="mt-3 p-4 bg-slate-900 rounded-xl text-center"><p className="text-xs text-slate-500">Select 2+ companies with coordinates from the map or list, then optimize.</p>{needGeo > 0 && <p className="text-xs text-amber-500 mt-1">{needGeo} companies still need geocoding</p>}</div>}
          </div>
          {route && <div className="flex-1 overflow-y-auto mobile-scroll p-4 space-y-0">
            {route.map((step, idx) => { const vis = visitedSlugs.has(step.company.slug), isCur = idx===routeIdx; return (
              <div key={step.company.slug} onClick={() => { setRouteIdx(idx); setActiveCompany(step.company); setActiveTab('map'); const [lng,lat]=getCoords(step.company); mapRef.current?.flyTo({center:[lng,lat],zoom:17,duration:400}); }}
                className={`flex gap-3 p-3 rounded-xl cursor-pointer transition-all mb-0 ${isCur ? 'bg-blue-500/10 border border-blue-500/30' : 'border border-transparent active:bg-slate-800/50'} ${vis?'opacity-40':''}`}>
                <div className="flex flex-col items-center pt-0.5">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${vis ? 'bg-green-500 text-white' : isCur ? 'bg-blue-600 text-white ring-4 ring-blue-500/20' : 'bg-slate-800 text-slate-400'}`}>{vis ? '✓' : idx+1}</div>
                  {idx < route.length-1 && <div className={`w-0.5 flex-1 my-1 min-h-4 ${vis?'bg-green-500/30':'bg-slate-800'}`} />}
                </div>
                <div className="flex-1 min-w-0 pb-3">
                  <p className={`text-sm font-medium truncate ${isCur?'text-blue-400':'text-white'}`}>{step.company.name}</p>
                  <p className="text-xs text-slate-500 truncate mt-0.5">{step.company.address || step.company.sector}</p>
                  <div className="flex items-center gap-3 mt-1"><span className="text-[10px] text-slate-500">+{formatDistance(step.distanceFromPrev)}</span><span className="text-[10px] text-slate-600">({formatDistance(step.cumulativeDist)})</span></div>
                  <div className="flex gap-1.5 mt-2">
                    <button onClick={e => { e.stopPropagation(); navigateTo(step.company); }} className="text-[10px] font-medium px-3 py-1.5 rounded-lg bg-green-500/10 text-green-400 active:bg-green-500/20">Navigate</button>
                    <button onClick={e => { e.stopPropagation(); vis ? markUnvisited(step.company.slug) : markVisited(step.company.slug); }} className={`text-[10px] font-medium px-3 py-1.5 rounded-lg ${vis ? 'bg-slate-800 text-slate-400' : 'bg-blue-500/10 text-blue-400'}`}>{vis ? 'Undo' : 'Done'}</button>
                  </div>
                </div>
              </div>
            );})}
          </div>}
        </div>
      )}
    </div>
  );
}