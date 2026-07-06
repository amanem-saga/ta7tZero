import { NextResponse } from "next/server";

const MAPBOX_TOKEN = process.env.MAPBOX_TOKEN;

export async function POST(req: Request) {
  try {
    const { addresses } = await req.json();
    if (!Array.isArray(addresses) || addresses.length === 0) {
      return NextResponse.json({ error: "No addresses provided" }, { status: 400 });
    }

    if (!MAPBOX_TOKEN) {
      return NextResponse.json({ error: "MAPBOX_TOKEN not configured" }, { status: 500 });
    }

    const results: Record<string, { lat: number; lng: number } | null> = {};
    let processed = 0;

    // Process in batches of 5 to respect rate limits
    const BATCH = 5;
    for (let i = 0; i < addresses.length; i += BATCH) {
      const batch = addresses.slice(i, i + BATCH);
      const promises = batch.map(async ({ slug, address, city }: { slug: string; address: string; city?: string }) => {
        if (!address) { results[slug] = null; return; }
        try {
          const q = `${address}${city ? `, ${city}` : ''}, Morocco`;
          const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(q)}.json?access_token=${MAPBOX_TOKEN}&country=ma&limit=1`;
          const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
          const data = await resp.json();
          if (data.features?.[0]?.center) {
            results[slug] = { lng: data.features[0].center[0], lat: data.features[0].center[1] };
          } else {
            results[slug] = null;
          }
        } catch {
          results[slug] = null;
        }
      });
      await Promise.all(promises);
      processed += batch.length;

      if (i + BATCH < addresses.length) {
        await new Promise(r => setTimeout(r, 300)); // Rate limit
      }
    }

    return NextResponse.json({ results, processed, total: addresses.length });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}