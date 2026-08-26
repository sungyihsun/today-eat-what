import fs from 'node:fs/promises';

const csvPath = new URL('../supabase/restaurants-import.csv', import.meta.url);
const supabaseUrl = process.env.SUPABASE_URL?.replace(/\/+$/, '');
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before running this script.');
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (quoted && char === '"' && next === '"') {
      value += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (!quoted && char === ',') {
      row.push(value);
      value = '';
    } else if (!quoted && (char === '\n' || char === '\r')) {
      if (char === '\r' && next === '\n') i += 1;
      row.push(value);
      if (row.some(Boolean)) rows.push(row);
      row = [];
      value = '';
    } else {
      value += char;
    }
  }

  if (value || row.length) {
    row.push(value);
    rows.push(row);
  }
  return rows;
}

function postgresArray(value) {
  if (!value) return [];
  if (!value.startsWith('{') || !value.endsWith('}')) {
    throw new Error(`Invalid PostgreSQL array value: ${value.slice(0, 80)}`);
  }
  return value
    .slice(1, -1)
    .split(',')
    .filter(Boolean)
    .map(item => item.replaceAll('\\"', '"').replaceAll('\\\\', '\\'))
    .map(item => item.replace(/^"|"$/g, ''));
}

const columns = [
  'name', 'area', 'lat', 'lng', 'categories', 'price', 'rating',
  'description', 'tags', 'phone', 'parking_tier', 'parking_sub',
  'photos', 'maps_url', 'hours',
];
const rows = parseCsv(await fs.readFile(csvPath, 'utf8'));
const header = rows.shift();
if (header?.join(',') !== columns.join(',')) {
  throw new Error('CSV columns do not match the restaurants table schema.');
}

const records = rows.map(row => {
  if (row.length !== columns.length) {
    throw new Error(`Invalid CSV row for ${row[0] || 'unknown restaurant'}.`);
  }
  return {
    name: row[0],
    area: row[1],
    lat: Number(row[2]),
    lng: Number(row[3]),
    categories: postgresArray(row[4]),
    price: row[5],
    rating: Number(row[6]),
    description: row[7],
    tags: postgresArray(row[8]),
    phone: row[9] || null,
    parking_tier: row[10],
    parking_sub: row[11] || null,
    photos: postgresArray(row[12]),
    maps_url: row[13],
    hours: JSON.parse(row[14] || '{}'),
  };
});

const endpoint = `${supabaseUrl}/rest/v1/restaurants`;
for (let offset = 0; offset < records.length; offset += 100) {
  const batch = records.slice(offset, offset + 100);
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`,
      'Content-Type': 'application/json',
      Prefer: 'resolution=merge-duplicates,return=minimal',
    },
    body: JSON.stringify(batch),
  });
  if (!response.ok) {
    throw new Error(`Import failed for rows ${offset + 1}-${offset + batch.length}: HTTP ${response.status} ${await response.text()}`);
  }
  console.log(`Imported ${offset + batch.length}/${records.length}`);
}

const countResponse = await fetch(`${endpoint}?select=id`, {
  headers: {
    apikey: serviceRoleKey,
    Authorization: `Bearer ${serviceRoleKey}`,
    Prefer: 'count=exact',
  },
});
if (!countResponse.ok) {
  throw new Error(`Import verification failed: HTTP ${countResponse.status}`);
}
console.log(`Import complete. ${countResponse.headers.get('content-range') || 'Row count unavailable'}`);
