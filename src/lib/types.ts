export interface Company {
  id: number;
  name: string;
  slug: string;
  ice: string | null;
  rc: string | null;
  sector: string | null;
  category: string | null;
  sub_category: string | null;
  address: string | null;
  city: string | null;
  phone1: string | null;
  phone2: string | null;
  phone3: string | null;
  fax: string | null;
  lat: number;
  lng: number;
  employees: string | null;
  status: string | null;
  url: string | null;
  description: string | null;
  date_creation: string | null;
  osm_url: string | null;
  has_real_coords: boolean;
}

export interface CompanyData {
  companies: Company[];
  sectors: string[];
  stats: {
    total: number;
    real_coords: number;
    default_coords: number;
    default_coord: [number, number];
  };
}

export type TabView = 'map' | 'list' | 'route';