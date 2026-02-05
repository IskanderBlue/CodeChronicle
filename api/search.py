"""
Search execution logic combining applicability resolution and building-code-mcp.
"""
from datetime import date
from typing import List, Dict, Any

from building_code_mcp import BuildingCodeMCP
from config.code_metadata import get_applicable_codes
from config.map_loader import map_cache


# Start the MCP server pointing to the configured maps directory
import os
# Default to sibling repo for local dev if not set
default_maps = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Canada_building_code_mcp/maps'))
maps_dir = os.environ.get('MCP_MAPS_DIR', default_maps)
mcp_server = BuildingCodeMCP(maps_dir=maps_dir)

SEARCH_RESULT_LIMIT = 10  # Unified limit for search results


def execute_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute search based on parsed parameters.
    """
    search_date_str = params.get('date')
    keywords = params.get('keywords', [])
    province = params.get('province', 'ON')
    
    try:
        search_date = date.fromisoformat(search_date_str)
    except (ValueError, TypeError):
        search_date = date.today()
        
    # Step 1: Resolve applicable codes
    applicable_codes = get_applicable_codes(province, search_date)
    
    if not applicable_codes:
        return {
            'error': f'No building codes found for {province} on {search_date}',
            'results': []
        }
        
    all_results = []
    
    # Step 2: Search each code
    for code_name in applicable_codes:
        # Check if it's a "current" code supported by the package natively
        # or if we need to load a historical map.
        
        # For MVP, building-code-mcp search_code() might only support current codes.
        # If the code_name is in our historical metadata, we might need a custom search
        # through the cached map if the package doesn't support custom map injection.
        
        # Let's assume the package handles standard codes like NBC 2020, OBC 2024.
        
        # Prefix extraction (OBC_2024 -> OBC)
        base_code = code_name.split('_')[0]
        
        try:
            # Use building-code-mcp search
            # We use base_code to ensure we only search within the resolved jurisdiction
            # mcp_server is our singleton instance of BuildingCodeMCP
            
            # TODO: For custom historical maps (e.g., OBC 2006) not natively in the package,
            # we need to ensure they are loaded into the MCP server or handled here.
            # For now, we wrap in try/except to avoid crashing if the code isn't found.
            
            search_response = mcp_server.search_code(
                query=" ".join(keywords),
                code=base_code,
                limit=SEARCH_RESULT_LIMIT
            )
            
            results = search_response.get('results', [])
            
            # If no results from package, check if we have a raw map cache for this edition
            # This is a fallback for stubs/historical data not yet fully integrated in MCP
            if not results:
                raw_map = map_cache.get_map(code_name)
                if raw_map:
                    # Simple keyword match on raw map for fallback
                    # This is very basic but ensures *something* returns for valid dates
                    # In a real impl, we'd have a better local search utility
                    print(f"Using fallback search for {code_name}")
                    # (Fallback logic omitted for brevity in MVP - just rely on MCP for now)

            # Add metadata to each result
            for result in results:
                result['code_edition'] = code_name
                result['source_date'] = search_date.isoformat()
                
            all_results.extend(results)
        except Exception as e:
            # If package fails (e.g., map not found), log it and continue
            print(f"Error searching {code_name}: {e}")
            
    # Step 3: Deduplicate and format
    unique_results = deduplicate_results(all_results)
    
    # Extract minimal metadata for history (top N)
    top_results_metadata = []
    for r in unique_results[:SEARCH_RESULT_LIMIT]:
        top_results_metadata.append({
            "code": r.get('code_edition', 'Unknown'),
            # Extract year from code string if possible, or source date
            "year": r.get('source_date', '')[:4], 
            "section_id": r.get('id', ''),
            "title": r.get('title', 'Untitled Section')
        })

    return {
        'applicable_codes': applicable_codes,
        'results': unique_results,
        'result_count': len(unique_results),
        'search_params': params,
        'top_results_metadata': top_results_metadata
    }


def deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate results based on section ID and code edition.
    """
    seen = set()
    unique = []
    
    for r in results:
        key = f"{r.get('code_edition')}:{r.get('id')}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
            
    return unique
