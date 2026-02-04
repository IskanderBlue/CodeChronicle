"""
Format search results for frontend display.
"""
from typing import List, Dict, Any


def format_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform raw search results into a format suitable for the frontend.
    """
    formatted = []
    
    for result in results:
        code_edition = result.get('code_edition', 'Unknown')
        is_obc = 'OBC' in code_edition
        
        section_data = {
            'id': result.get('id'),
            'title': result.get('title', 'No title'),
            'code': code_edition,
            'page': result.get('page'),
            'text_available': is_obc,  # OBC allows full text storage
            'text': result.get('text') if is_obc else None,
            'bbox': result.get('bbox'),  # For PDF extraction (BYOD)
            'score': result.get('score', 0),
        }
        
        # Amendment tracking (Placeholder for now)
        section_data['amendments'] = get_amendments_for_section(
            result.get('id'), 
            code_edition
        )
        
        formatted.append(section_data)
        
    # Sort by relevance score (descending)
    formatted.sort(key=lambda x: x.get('score', 0), reverse=True)
    
    return formatted


def get_amendments_for_section(section_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """
    Mock function to retrieve amendments for a specific section.
    Real data would come from the historical metadata or a DB.
    """
    # Placeholder: In a real implementation, we'd check CODE_EDITIONS 
    # and match amendment dates to the search date.
    return []
