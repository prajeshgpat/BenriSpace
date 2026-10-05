-- BenriSpace migration 0015: composite GiST index for per-category nearest-neighbour search.
-- NOT yet applied. Additive and idempotent. Needs the btree_gist extension (available on
-- Supabase). The on-demand point scoring query (scoring/point.py build_live_sql) runs
-- `where category = X order by geom <-> point limit 6` ~24 times per point; with the plain
-- geom GiST index each of those walks past every other category's rows (measured on a copy
-- of places: 6 categories, 111 ms -> 15 ms with this index).

create extension if not exists btree_gist;

create index if not exists places_category_geom_gist on places using gist (category, geom);
