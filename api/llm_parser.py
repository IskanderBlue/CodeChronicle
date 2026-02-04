"""
Claude-based query parser to extract structured search parameters from natural language.
"""
import anthropic
from django.conf import settings
from typing import Dict, Any, List, Optional
from datetime import date


from config.keywords import VALID_KEYWORDS


# Tool definition for Claude
PARSE_QUERY_TOOL = {
    "name": "parse_building_code_query",
    "description": "Extract search parameters from natural language building code question",
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "format": "date",
                "description": "Date of construction or renovation (YYYY-MM-DD). Use today's date if not mentioned."
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Valid building code keywords. Only use terms from the master keyword list provided in system prompt."
            },
            "building_type": {
                "type": "string",
                "enum": ["residential", "commercial", "industrial", "assembly", "institutional"],
                "description": "Type of building if mentioned"
            },
            "province": {
                "type": "string",
                "enum": ["ON", "BC", "AB", "QC", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"],
                "description": "Canadian province (default: ON)"
            }
        },
        "required": ["date", "keywords"]
    }
}

SYSTEM_PROMPT = f"""You are a building code query parser.

Extract from user query:
1. Date (when was building constructed/renovated? format YYYY-MM-DD)
2. Keywords (what code topics are relevant?)
3. Building type (if mentioned)
4. Province (if mentioned, default ON)

CRITICAL: Keywords must ONLY come from this master list:
{', '.join(VALID_KEYWORDS)}

Do NOT use keywords outside this list. If query contains no valid keywords, return empty array for keywords.
If the user mentions a year but not a specific date, assume January 1st of that year (YYYY-01-01).
If no date or year is mentioned, use today's date: {date.today().isoformat()}."""


def parse_user_query(query: str) -> Dict[str, Any]:
    """
    Parse natural language query into structured parameters using Claude.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    try:
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1000,
            tools=[PARSE_QUERY_TOOL],
            tool_choice={"type": "tool", "name": "parse_building_code_query"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}]
        )
    except anthropic.AuthenticationError:
        raise ValueError("Invalid Anthropic API Key. Please verify the ANTHROPIC_API_KEY in your .env file.")
    except Exception as e:
        raise ValueError(f"LLM parsing failed: {str(e)}")
    
    # Extract tool use
    for block in response.content:
        if block.type == "tool_use":
            params = block.input
            
            # Validate keywords against master list (extra safety)
            keywords = params.get('keywords', [])
            valid_keywords = [k for k in keywords if k.lower() in VALID_KEYWORDS]
            
            if not valid_keywords:
                # If no valid keywords, try to use high-level terms if they were in the original query
                # or raise a specific error that the user needs to be more specific.
                raise ValueError(
                    f"Query does not contain recognized building code keywords. "
                    f"Try terms like: fire safety, structural, plumbing, electrical."
                )
            
            params['keywords'] = valid_keywords
            # Ensure province defaults to ON if missing
            if 'province' not in params:
                params['province'] = 'ON'
                
            return params
            
    raise ValueError("Could not parse query parameters.")
