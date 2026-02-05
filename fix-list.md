# Fix List

- api/search.py 's default_maps, maps_dir should check s3 when running in production & should reference a variable re: where to find the maps when running locally.
- we want more detail returned from search_results; maybe title too.
- need loading indicator when search is running. 