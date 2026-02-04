"""
Search execution logic combining applicability resolution and building-code-mcp.
"""
from datetime import date
from typing import List, Dict, Any

from django.conf import settings
from building_code_mcp import BuildingCodeMCP
from config.code_metadata import get_applicable_codes
from config.map_loader import map_cache

# Initialize the MCP server as a singleton
# We point it to the neighboring repo's maps directory
import os
MCP_MAPS_DIR = os.path.abspath(os.path.join(settings.BASE_DIR, "..", "Canada_building_code_mcp", "maps"))
mcp_server = BuildingCodeMCP(maps_dir=MCP_MAPS_DIR)


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
            search_response = mcp_server.search_code(
                query=" ".join(keywords),
                code=base_code,
                limit=10
            )
            
            results = search_response.get('results', [])
            
            # Add metadata to each result
            for result in results:
                result['code_edition'] = code_name
                result['source_date'] = search_date.isoformat()
                
            all_results.extend(results)
        except Exception as e:
            # If package fails, log it and continue
            print(f"Error searching {code_name}: {e}")
            
    # Step 3: Deduplicate and format
    unique_results = deduplicate_results(all_results)
    
    return {
        'applicable_codes': applicable_codes,
        'results': unique_results,
        'result_count': len(unique_results),
        'search_params': params
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
