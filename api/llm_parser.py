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



def get_prompt_hash(content: str) -> str:
    """Generate SHA-256 hash of the prompt content."""
    import hashlib
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_query_hash(query: str) -> str:
    """Generate SHA-256 hash of the normalized query."""
    import hashlib
    # Normalize: lowercase, strip whitespace
    normalized = query.lower().strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def parse_user_query(query: str) -> Dict[str, Any]:
    """
    Parse natural language query into structured parameters using Claude.
    Checks QueryCache before calling API.
    """
    from core.models import QueryCache, QueryPrompt
    
    # 0. Prepare hashes
    query_hash = get_query_hash(query)
    prompt_content = SYSTEM_PROMPT + str(PARSE_QUERY_TOOL)
    prompt_hash = get_prompt_hash(prompt_content)
    
    # 1. Check Cache
    cached = QueryCache.objects.filter(
        query_hash=query_hash,
        prompt__prompt_hash=prompt_hash
    ).first()
    
    if cached:
        # Cache Hit
        cached.hits += 1
        cached.save(update_fields=['hits'])
        return cached.parsed_params

    # 2. Cache Miss - Call API
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
            
            # 3. Save to Cache
            # Ensure Prompt exists
            prompt_obj, _ = QueryPrompt.objects.get_or_create(
                prompt_hash=prompt_hash,
                defaults={'content': prompt_content}
            )
            
            QueryCache.objects.create(
                query_hash=query_hash,
                raw_query=query,
                parsed_params=params,
                llm_model=settings.CLAUDE_MODEL,
                prompt=prompt_obj
            )
                
            return params
            
    raise ValueError("Could not parse query parameters.")
