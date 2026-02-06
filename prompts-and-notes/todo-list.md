# TODO list

- api/search.py 's default_maps, maps_dir should check s3 when running in production & should reference a variable re: where to find the maps when running locally.
- we want more detail returned from search_results; maybe title too.
- need loading indicator when search is running. 
- "Full text not available for this code in the Free tier" displays if no pdf available even for pro.
- periodically check for style violations.
- implment/test pdf display.
    - test with NBC 2025.
    - what does mcp return for ontario/html codes?

## Eventually:
- separate repo for terraform infrastructure.
- separate repo for populating historical code maps.
- implement stripe subscriptions.
