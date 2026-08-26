# Supabase setup

This project currently runs as a static GitHub Pages site. The files in this
folder prepare the free Supabase backend without requiring a server runtime.

## Setup

1. Create a free project at [Supabase](https://supabase.com).
2. Open **SQL Editor** and run [`schema.sql`](./schema.sql).
3. Copy [`config.example.js`](./config.example.js) to `config.js`.
4. Put the project URL and publishable (anon) key in `config.js`.
5. Add `config.js` to the site before the application script when frontend
   Supabase integration is enabled.

## Import the existing restaurants

The generated [`restaurants-import.csv`](./restaurants-import.csv) contains the
406 restaurant records currently embedded in `index.html`. In Supabase, open
**Table Editor → restaurants → Import data from CSV**, select that file, and
map the columns to their matching fields. Keep the `id`, `created_at`, and
`updated_at` columns at their defaults. The `categories`, `tags`, and `photos`
columns use PostgreSQL array syntax; `hours` contains JSON objects. Import them
into their corresponding array/`jsonb` columns.

`config.js` is intentionally ignored by Git so project credentials are not
committed. The anon key is safe for browser use only when the RLS policies in
`schema.sql` remain enabled. Never use a `service_role` key in the frontend.

The `restaurants` table is publicly readable. The `favorites` table is private
to authenticated users, allowing favorites to sync across devices after login
is added to the frontend.
