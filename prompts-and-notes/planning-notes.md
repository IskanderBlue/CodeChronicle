# Historical Canadian Building Code Search - Implementation Plan

## Project Overview

Build a web application that allows engineers to search historical Canadian building codes (NBC and OBC) to determine code compliance for buildings constructed or renovated at specific points in time.

### Key Differentiator
Unlike existing tools (CanCodes.ca), this application provides:
- **Historical code versions** dating back to 2003 (initially) with expansion to 1975+
- **Time-aware queries**: "What code applied in 1993?"
- **Provincial vs Federal separation**: Display OBC amendments fully, NBC via coordinate index + BYOD

### Business Model
- **Free tier**: 10 searches per day, basic keyword search, section metadata only
- **Pro tier** ($30-50/month): Unlimited searches, full historical access (back to 1975 eventually)
- **Site licenses**: For engineering firms - license to run application on their own infrastructure with their own data

Note: Site licenses allow firms to:
- Host the application internally
- Customize for internal workflows
- Typically priced at $500-2000/year per firm

---

## Technical Architecture

### Stack Overview
```
Frontend:
├── Django templates (Jinja2)
├── HTMX (dynamic updates)
├── Alpine.js (minimal client-side interactivity)
└── Tailwind CSS (responsive styling)

Backend:
├── Django 5.x
├── Django Ninja (REST API)
├── Python 3.12+
└── building-code-mcp (imported as dependency)

Database:
└── PostgreSQL (users, subscriptions, code-year mappings)

Infrastructure:
├── GCP (Terraform)
├── Compute Engine VM (e2-micro)
├── Neon Postgres (managed)
└── Cloudflare (DNS + proxy + Origin CA)

AI/LLM:
└── Anthropic Claude API (query parsing only - synthesis is post-MVP)

Payment:
└── Stripe (subscriptions, webhooks)
```

## Data Model

### PostgreSQL Schema

```python
# Django models

class User(AbstractUser):
    stripe_customer_id = CharField(max_length=255, null=True)
    
class Subscription(Model):
    user = ForeignKey(User, on_delete=CASCADE)
    stripe_subscription_id = CharField(max_length=255)
    status = CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('past_due', 'Past Due')
    ])
    plan = CharField(max_length=20, choices=[
        ('free', 'Free'),
        ('pro', 'Pro')
    ])
    current_period_end = DateTimeField()

class SearchHistory(Model):
    user = ForeignKey(User, on_delete=CASCADE)
    query = TextField()
    parsed_params = JSONField()  # Store LLM parsed parameters
    timestamp = DateTimeField(auto_now_add=True)
    result_count = IntegerField()
```

### Code Editions (Database)

Code editions and amendments are stored in Postgres and loaded from
`config/metadata.json` via `python manage.py load_code_metadata`.
Lookups for “what applied on date X” use database queries (see
`config/code_metadata.py:get_applicable_codes`).

**Amendment handling:**
- Amendments are metadata for display only ("this regulation was filed on X date")
- Editions include amendment metadata for their date range

### Map Storage (Postgres)

Maps are stored in Postgres (Neon) using `CodeMap` + `CodeMapNode` tables. Source
JSON files live in the mapping repo and are loaded into the DB via management
commands.

**Source maps:**
- `CodeChronicle-Mapping/maps/*.json` (OBC/NBC maps)
- `config/metadata.json` (editions, amendments, province mappings)

**Loading into Postgres:**
```bash
python manage.py load_code_metadata --source config/metadata.json
python manage.py load_maps --source ../CodeChronicle-Mapping/maps
```

### Map Access

API searches read directly from `CodeMapNode` with ORM queries. Add caching later
only if profiling shows DB hot spots.

---

## Implementation Phases

### Phase 1: Infrastructure & Data Foundation (Weeks 1-2)

**Week 1: Infrastructure Setup**

1. **Terraform Configuration**
   ```hcl
   # CodeChronicle-terraform/envs/prod/main.tf
   # Modules: network, compute, secrets, neon, cloudflare
   module "compute" {
     source       = "../../modules/compute"
     machine_type = "e2-micro"
   }
   ```

2. **Django Project Setup**
   ```bash
   django-admin startproject building_code_search
   cd building_code_search
   python -m venv venv
   source venv/bin/activate
   
   # requirements.txt
   Django>=5.0
   django-ninja>=1.0
   psycopg2-binary
   building-code-mcp>=1.2.0
   dj-stripe
   anthropic
   python-dotenv
   gunicorn
   ```

3. **PostgreSQL Database Setup**
   ```python
   # settings.py
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',
           'NAME': os.environ.get('DB_NAME'),
           'USER': os.environ.get('DB_USER'),
           'PASSWORD': os.environ.get('DB_PASSWORD'),
           'HOST': os.environ.get('DB_HOST'),
           'PORT': '5432',
       }
   }
   ```

**Week 2: Data Acquisition & Map Building**

This is the only moat we get. Separate repository for scraper & map updating. Rest goes into public repo.

1. **e-Laws Scraper for OBC (2004-2024)**
   - Scrape HTML from e-Laws and emit JSON map files into
     `CodeChronicle-Mapping/maps/`.
   - Load into Postgres with:
     `python manage.py load_maps --source ../CodeChronicle-Mapping/maps`

2. **Import NBC Maps from building-code-mcp**
   - Generate/normalize NBC map JSONs from `building-code-mcp`.
   - Load into Postgres with the same `load_maps` command.

### Phase 2: Core Search Engine (Weeks 3-4)

**Week 3: Query Processing**

1. **LLM Query Parser** (Claude function calling)
   ```python
   # api/llm_parser.py
   import anthropic
   from django.conf import settings
   
   client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
   
   # Master list of valid building code keywords
   VALID_KEYWORDS = [
       # Fire safety
       'fire', 'flame', 'smoke', 'alarm', 'detector', 'sprinkler', 'extinguisher',
       'separation', 'resistance', 'egress', 'exit', 'escape',
       
       # Structural
       'structural', 'load', 'bearing', 'foundation', 'footing', 'beam', 'column',
       'joist', 'rafter', 'truss', 'slab', 'wall', 'floor', 'roof',
       
       # Plumbing
       'plumbing', 'drainage', 'water', 'supply', 'sewage', 'fixture', 'pipe',
       'drain', 'vent', 'trap', 'backflow',
       
       # Electrical
       'electrical', 'wiring', 'circuit', 'panel', 'outlet', 'switch', 'grounding',
       'bonding', 'service', 'voltage',
       
       # HVAC
       'heating', 'ventilation', 'air', 'conditioning', 'hvac', 'duct', 'furnace',
       
       # Building envelope
       'insulation', 'thermal', 'window', 'door', 'glazing', 'weatherproofing',
       
       # Accessibility
       'accessible', 'barrier-free', 'ramp', 'handrail', 'guard', 'stair',
       
       # Occupancy
       'residential', 'commercial', 'industrial', 'assembly', 'institutional',
       'dwelling', 'unit', 'occupancy'
   ]
   
   PARSE_QUERY_TOOL = {
       "name": "parse_building_code_query",
       "description": "Extract search parameters from natural language building code question",
       "input_schema": {
           "type": "object",
           "properties": {
               "year": {
                   "type": "integer",
                   "description": "Year when building was constructed or renovated"
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
                   "enum": ["ON", "BC", "AB", "QC"],
                   "description": "Canadian province (default: ON)"
               }
           },
           "required": ["year", "keywords"]
       }
   }
   
   SYSTEM_PROMPT = f"""You are a building code query parser.

   Extract from user query:
   1. Year (when was building constructed/renovated?)
   2. Keywords (what code topics are relevant?)
   3. Building type (if mentioned)
   4. Province (if mentioned, default ON)

   CRITICAL: Keywords must ONLY come from this master list:
   {', '.join(VALID_KEYWORDS)}

   Do NOT use keywords outside this list. If query contains no valid keywords, return empty array."""
   
   def parse_user_query(query: str) -> dict:
       """
       Parse natural language query into structured search parameters
       
       Example:
       Input: "Fire safety for house built in 1993"
       Output: {
           "year": 1993,
           "keywords": ["fire", "safety"],
           "building_type": "residential",
           "province": "ON"
       }
       
       Raises ValueError if no valid keywords found
       """
       response = client.messages.create(
           model="claude-sonnet-4-20250514",
           max_tokens=1000,
           tools=[PARSE_QUERY_TOOL],
           system=SYSTEM_PROMPT,
           messages=[{
               "role": "user",
               "content": query
           }]
       )
       
       # Extract tool use
       for block in response.content:
           if block.type == "tool_use":
               params = block.input
               
               # Validate keywords against master list
               keywords = params.get('keywords', [])
               valid_keywords = [k for k in keywords if k.lower() in VALID_KEYWORDS]
               
               if not valid_keywords:
                   raise ValueError(
                       f"Query does not contain valid building code keywords. "
                       f"Try terms like: fire, structural, plumbing, electrical"
                   )
               
               params['keywords'] = valid_keywords
               return params
       
       raise ValueError("Could not parse query")
   
2. **Code Edition Resolver**



   Note: will need to amend to require specific date, not year.
   ```python
   
   def get_applicable_codes(province: str, year: int) -> list[str]:
       """
       Determine which code editions were in effect at a given time
       
       Example: province="ON", year=1993
       Returns: ["OBC_1990", "NBC_1990"]
       
       Logic:
       - Find most recent OBC before/at year
       - Find most recent NBC before/at year
       """
       codes = []
       
       # Provincial code (OBC, BCBC, etc.)
       if province:
           provincial_code = get_applicable_code(f'{province}BC', year)
           if provincial_code:
               codes.append(f"{province}BC_{provincial_code['year']}")
       
       # Federal code (NBC)
       federal_code = get_applicable_code('NBC', year)
       if federal_code:
           codes.append(f"NBC_{federal_code['year']}")
       
       return codes
   ```

3. **Search Execution with building-code-mcp**

   Note: will want to search all valid codes at the same time, not in loop.

   ```python
   # api/search.py
   from config.map_loader import map_cache
   from building_code_mcp import search_code
   
   def execute_search(params: dict) -> dict:
       """
       Execute search using parsed parameters
       
       Flow:
       1. Get applicable codes for year
       2. Search each code using building-code-mcp
       3. Combine and return results
       """
       year = params['year']
       keywords = params['keywords']
       province = params.get('province', 'ON')
       
       # Step 1: Resolve which codes to search
       applicable_codes = get_applicable_codes(province, year)
       
       if not applicable_codes:
           return {
               'error': f'No building codes found for {province} in {year}',
               'results': []
           }
       
       # Step 2: Search each code
       all_results = []
       
       for code_name in applicable_codes:
           # Check if we have this map loaded
           if not map_cache.get_map(code_name):
               continue
           
           # Use building-code-mcp search
           # This handles fuzzy matching, keyword indexing, etc.
           results = search_code(
               query=" ".join(keywords),
               code=code_name,
               limit=20  # Top 20 results per code
           )
           
           # Add metadata
           for result in results:
               result['code_edition'] = code_name
               result['year'] = year
           
           all_results.extend(results)
       
       # Step 3: Deduplicate and rank
       # (NBC and OBC might have same section numbers)
       unique_results = deduplicate_results(all_results)
       
       return {
           'applicable_codes': applicable_codes,
           'results': unique_results,
           'result_count': len(unique_results)
       }
   
   ```

**Week 4: Result Formatting**

1. **Format Results for Display**

   Note: amendments section will need updating; part of CODE_EDITION.

   ```python
   # api/formatters.py
   
   def format_search_results(results: list) -> list:
       """
       Transform raw search results for frontend display
       
       For each result:
       - Section ID and title
       - Page number (for reference)
       - Text (if available - OBC only)
       - Coordinates (for NBC BYOD)
       - Related amendments (if any)
       """
       formatted = []
       
       for result in results:
           section_data = {
               'id': result['id'],
               'title': result.get('title', 'No title'),
               'code': result['code_edition'],
               'page': result.get('page'),
               'text_available': 'OBC' in result['code_edition'],
               'text': None,
               'bbox': result.get('bbox'),  # For NBC PDF extraction
           }
           
           # Include full text for OBC (Crown copyright allows it)
           if section_data['text_available']:
               section_data['text'] = result.get('text', result.get('full_text'))
           
           # Check for amendments affecting this section
           amendments = get_amendments_for_section(
               result['id'],
               result['code_edition']
           )
           
           section_data['amendments'] = [
               {
                   'regulation': a.regulation,
                   'effective_date': str(a.effective_date),
                   'description': a.description
               }
               for a in amendments
           ]
           
           formatted.append(section_data)
       
       return formatted
   
   ```

### Phase 3: Django Backend API (Week 5)

1. **Django Ninja API Endpoints**

   ```python
   # api/views.py
   from ninja import NinjaAPI
   from ninja.security import django_auth
   from .llm_parser import parse_user_query
   from .search import execute_search
   from .formatters import format_search_results
   
   api = NinjaAPI()
   
   @api.post("/search", auth=django_auth)
   def search(request, query: str):
       """
       Main search endpoint (MVP - Simple mode only)
       
       Returns: Structured section results with metadata
       """
       user = request.user
       
       # Step 1: Parse natural language with LLM
       try:
           params = parse_user_query(query)
       except ValueError as e:
           return {
               "error": str(e),
               "suggestion": "Try including specific code terms like 'fire safety', 'structural', 'plumbing'"
           }
       
       # Step 2: Execute search
       search_results = execute_search(params)
       
       if search_results.get('error'):
           return search_results
       
       # Step 3: Format for display
       formatted_results = format_search_results(search_results['results'])
       
       # Save to history
       SearchHistory.objects.create(
           user=user,
           query=query,
           parsed_params=params,
           result_count=len(formatted_results)
       )
       
       return {
           "query": query,
           "parsed_params": params,
           "applicable_codes": search_results['applicable_codes'],
           "results": formatted_results,
           "result_count": len(formatted_results)
       }
   
   @api.get("/history", auth=django_auth)
   def get_search_history(request):
       """Return user's recent searches"""
       history = SearchHistory.objects.filter(
           user=request.user
       ).order_by('-timestamp')[:20]
       
       return {
           "history": [
               {
                   "query": h.query,
                   "timestamp": h.timestamp.isoformat(),
                   "result_count": h.result_count
               }
               for h in history
           ]
       }
   
   # /api/codes endpoint removed (use code metadata + DB for code listings)
   ```

2. **Subscription Middleware**
   ```python
   # middleware/subscription.py
   from django.http import JsonResponse
   from django.utils import timezone
   
   class SubscriptionMiddleware:
       def __init__(self, get_response):
           self.get_response = get_response
       
       def __call__(self, request):
           if request.path.startswith('/api/search'):
               user = request.user
               
               if not user.is_authenticated:
                   return JsonResponse(
                       {"error": "Authentication required"}, 
                       status=401
                   )
               
               # Check subscription status
               if not hasattr(user, 'subscription'):
                   # Free tier - enforce limits
                   return self.enforce_free_tier_limits(request)
               
               if user.subscription.status != 'active':
                   return JsonResponse(
                       {"error": "Subscription expired or inactive"}, 
                       status=403
                   )
           
           return self.get_response(request)
       
       def enforce_free_tier_limits(self, request):
           """Free tier: 10 searches per day"""
           from api.models import SearchHistory
           
           today_searches = SearchHistory.objects.filter(
               user=request.user,
               timestamp__date=timezone.now().date()
           ).count()
           
           if today_searches >= 10:
               return JsonResponse({
                   "error": "Daily limit reached (10 searches)",
                   "upgrade_url": "/pricing"
               }, status=429)
           
           return None
   ```

### Phase 4: Frontend (Week 6)

1. **Django Templates + HTMX**
   ```html
   <!-- templates/search.html -->
   <!DOCTYPE html>
   <html>
   <head>
       <title>Building Code Search</title>
       <script src="https://unpkg.com/htmx.org@1.9.10"></script>
       <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
       <script src="https://cdn.tailwindcss.com"></script>
   </head>
   <body class="bg-gray-50">
       <div class="container mx-auto px-4 py-8 max-w-4xl">
           <h1 class="text-3xl font-bold mb-2">Historical Building Code Search</h1>
           <p class="text-gray-600 mb-8">
               Find code requirements for buildings constructed at specific dates
           </p>
           
           <!-- Search Form -->
           <div class="bg-white rounded-lg shadow p-6 mb-8">
               <form hx-post="/api/search" 
                     hx-target="#results" 
                     hx-indicator="#loading"
                     class="space-y-4">
                   
                   <div>
                       <label class="block text-sm font-medium mb-2">
                           Ask about building codes:
                       </label>
                       <input type="text" 
                              name="query" 
                              placeholder="e.g., Fire safety requirements for a house built in 1993"
                              class="w-full border rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500"
                              required>
                       <p class="text-sm text-gray-500 mt-1">
                           Include: year built, topic (fire, structural, plumbing), and building type
                       </p>
                   </div>
                   
                   <button type="submit" 
                           class="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition">
                       Search Codes
                   </button>
                   
                   <div id="loading" class="htmx-indicator flex items-center gap-2 text-blue-600">
                       <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                           <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                           <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                       </svg>
                       Searching...
                   </div>
               </form>
           </div>
           
           <!-- Results -->
           <div id="results"></div>
       </div>
   </body>
   </html>
   ```

   ```html
   <!-- templates/partials/results.html -->
   {% if error %}
   <div class="bg-red-50 border border-red-200 rounded-lg p-6 mb-8">
       <h2 class="text-lg font-bold text-red-800 mb-2">Search Error</h2>
       <p class="text-red-700">{{ error }}</p>
       {% if suggestion %}
       <p class="text-sm text-red-600 mt-2">{{ suggestion }}</p>
       {% endif %}
   </div>
   {% else %}
   
   <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
       <div class="text-sm">
           <p><strong>Searching:</strong> {{ applicable_codes|join:", " }}</p>
           <p><strong>Found:</strong> {{ result_count }} sections</p>
       </div>
   </div>
   
   <div class="space-y-4" x-data="{ expanded: {} }">
       {% for result in results %}
       <div class="bg-white rounded-lg shadow-md p-6 border-l-4 border-blue-500">
           <div class="flex justify-between items-start mb-3">
               <div>
                   <h3 class="font-bold text-lg text-gray-900">
                       {{ result.code }} Section {{ result.id }}
                   </h3>
                   <p class="text-gray-700 font-medium">{{ result.title }}</p>
                   <p class="text-sm text-gray-500">Page {{ result.page }}</p>
               </div>
               
               {% if result.text_available %}
               <button @click="expanded['{{ result.id }}'] = !expanded['{{ result.id }}']"
                       class="text-blue-600 hover:text-blue-800 text-sm font-medium">
                   <span x-show="!expanded['{{ result.id }}']">▼ Show text</span>
                   <span x-show="expanded['{{ result.id }}']">▲ Hide text</span>
               </button>
               {% else %}
               <span class="text-sm text-gray-500 italic bg-gray-100 px-3 py-1 rounded">
                   NBC - PDF required
               </span>
               {% endif %}
           </div>
           
           {% if result.text_available %}
           <div x-show="expanded['{{ result.id }}']" 
                x-cloak
                class="mt-4 p-4 bg-gray-50 rounded border border-gray-200">
               <pre class="whitespace-pre-wrap text-sm font-mono">{{ result.text }}</pre>
           </div>
           {% endif %}
           
           {% if result.amendments %}
           <div class="mt-4 pt-4 border-t border-gray-200">
               <p class="text-sm font-semibold text-gray-700 mb-2">Amendments:</p>
               <ul class="text-sm text-gray-600 space-y-1">
                   {% for amend in result.amendments %}
                   <li class="flex gap-2">
                       <span class="font-mono">{{ amend.regulation }}</span>
                       <span>({{ amend.effective_date }})</span>
                       <span class="text-gray-500">{{ amend.description }}</span>
                   </li>
                   {% endfor %}
               </ul>
           </div>
           {% endif %}
       </div>
       {% endfor %}
   </div>
   {% endif %}
   ```

2. **Mobile Responsiveness**
   ```html
   <!-- Tailwind handles responsive design -->
   <div class="container mx-auto px-4">
       <!-- px-4 gives padding on mobile -->
       <!-- max-w-4xl keeps readable width on desktop -->
   </div>
   
   <!-- Responsive grid example (if needed later) -->
   <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
       <!-- 1 column mobile, 2 tablet, 3 desktop -->
   </div>
   ```

3. **Text Extraction**

   Use PDF.js (& possibly pdf-text-reader, pdfjs-text-layer-builder) on the client-side to extract text from the PDF files. 

   ```javascript
   // Example of PDF.js usage
   import pdfjsLib from 'pdfjs-dist';
   
   pdfjsLib.getDocument('path/to/your/file.pdf').promise.then(function(pdf) {
       pdf.getPage(1).then(function(page) {
           page.getTextContent().then(function(textContent) {
               console.log(textContent.items);
           });
       });
   });
   ```

**Note:** AI synthesis UI will be added post-MVP as a Pro feature with a separate "Ask AI" button.

### Phase 5: Payments & Auth (Week 7)

1. **Stripe Integration**
   ```python
   # settings.py
   INSTALLED_APPS += ['djstripe']
   
   STRIPE_LIVE_SECRET_KEY = os.environ.get("STRIPE_LIVE_SECRET_KEY")
   STRIPE_TEST_SECRET_KEY = os.environ.get("STRIPE_TEST_SECRET_KEY")
   DJSTRIPE_WEBHOOK_SECRET = os.environ.get("DJSTRIPE_WEBHOOK_SECRET")
   
   # models.py (dj-stripe handles most of this)
   from djstripe.models import Customer, Subscription
   
   # User model extension
   class UserProfile(models.Model):
       user = models.OneToOneField(User, on_delete=models.CASCADE)
       stripe_customer = models.ForeignKey(Customer, null=True, on_delete=models.SET_NULL)
       
       @property
       def has_active_subscription(self):
           if not self.stripe_customer:
               return False
           return self.stripe_customer.subscriptions.filter(
               status='active'
           ).exists()
   ```

2. **Webhook Handlers**
   ```python
   # webhooks.py
   from djstripe import webhooks
   
   @webhooks.handler("customer.subscription.created")
   def handle_subscription_created(event, **kwargs):
       subscription = event.data["object"]
       customer = subscription["customer"]
       
       # Link to Django user
       profile = UserProfile.objects.get(stripe_customer__id=customer)
       # Send welcome email
       send_welcome_email(profile.user)
   
   @webhooks.handler("customer.subscription.deleted")
   def handle_subscription_cancelled(event, **kwargs):
       subscription = event.data["object"]
       # User can still access until period_end
       # dj-stripe handles the status update automatically
   
   @webhooks.handler("invoice.payment_failed")
   def handle_payment_failed(event, **kwargs):
       invoice = event.data["object"]
       customer = invoice["customer"]
       
       profile = UserProfile.objects.get(stripe_customer__id=customer)
       send_payment_failed_email(profile.user)
   ```

3. **Pricing Page**
   ```python
   # views.py
   @api.get("/pricing")
   def pricing(request):
       plans = [
           {
               "name": "Free",
               "price": 0,
               "features": [
                   "10 searches per day",
                   "Keyword search only",
                   "View section locations"
               ]
           },
           {
               "name": "Pro",
               "price": 30,
               "stripe_price_id": "price_xxxxx",
               "features": [
                   "Unlimited searches",
                   "AI-powered answers",
                   "Full historical access",
                   "Export results"
               ]
           }
       ]
       return render(request, 'pricing.html', {'plans': plans})
   ```

### Phase 6: Testing & Deployment (Week 8)

1. **Unit Tests**
   ```python
   # tests/test_search.py
   from django.test import TestCase
   from api.llm_parser import parse_natural_language_query
   
   class QueryParserTests(TestCase):
       def test_simple_query(self):
           result = parse_natural_language_query(
               "Fire safety for 1993 house"
           )
           self.assertEqual(result['year'], 1993)
           self.assertIn('fire', result['keywords'])
           self.assertEqual(result['building_type'], 'residential')
   ```

2. **Terraform Deployment**
   ```bash
   cd CodeChronicle-terraform/envs/prod
   terraform init
   terraform plan -var-file=prod.tfvars
   terraform apply -var-file=prod.tfvars
   
   # Output will include:
   # - public_ip
   # - domain_name
   # - neon_connection_string (sensitive)
   ```

3. **Application Deployment**
   ```bash
   # On GCE VM
   cd /opt/codechroniclenet
   docker compose pull
   docker compose up -d
   
   # Run migrations and seed data
   docker exec -it <container> python manage.py migrate
   docker exec -it <container> python manage.py load_code_metadata --source config/metadata.json
   docker exec -it <container> python manage.py load_maps --source /opt/codechronicle-mapping/maps
   ```

4. **Nginx Configuration**
   ```nginx
   # /etc/nginx/sites-available/buildingcode
   server {
       listen 443 ssl;
       server_name app.yourdomain.com;
       
       ssl_certificate /etc/nginx/certs/origin.crt;
       ssl_certificate_key /etc/nginx/certs/origin.key;
       
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-Proto https;
       }
       
       location /static/ {
           alias /var/www/building-code-search/static/;
       }
   }
   ```

---

## Data Acquisition Details

### Ontario Building Code (2004-2024)

**Source**: e-Laws (https://www.ontario.ca/laws)

**Process**:
1. Identify regulation numbers for each code edition
2. Use e-Laws "Versions" feature to get point-in-time snapshots
3. Parse HTML to extract sections, tables, amendments
4. Store full text in Neo4j (Crown copyright allows reproduction)

**Key Regulations**:
- OBC 2024: O. Reg. 163/24
- OBC 2012: O. Reg. 332/12
- OBC 2006: O. Reg. 350/06

**Amendment Tracking**:
- Use CodeNews.ca table as reference for amendment descriptions
- e-Laws provides official amendment text
- Build amendment graph in Neo4j

### National Building Code (2020, 2015, 2010, 2005)

**Source**: building-code-mcp package + NRC Publications Archive

**Process**:
1. Import coordinate indices from building-code-mcp
2. Store section IDs, page numbers, bounding boxes
3. Do NOT store full text (NRC copyright restriction)
4. Implement BYOD (Bring Your Own Document) for text extraction

**BYOD Flow**:
1. User specifies path to legally-obtained NBC PDF
2. Store path in user config
3. When displaying results, extract text using PDF.js (& possibly pdf-text-reader, pdfjs-text-layer-builder) at stored coordinates
4. Text extraction happens on-demand, never stored permanently

### Future Expansion (1975-2003)

**Sources** (when implementing):
1. CodeNews.ca - has 1975 PDF
2. Contact Alek Antoniuk for 1983, 1986, 1990, 1997 editions
3. University law libraries for physical copies
4. Ontario Archives for missing editions?

**OCR Pipeline** (if needed):
```python
# scripts/ocr_pipeline.py
import pytesseract
from pdf2image import convert_from_path

def ocr_building_code(pdf_path: str) -> dict:
    """
    OCR scanned building code PDFs
    """
    # Convert PDF to images
    images = convert_from_path(pdf_path, dpi=600)
    
    sections = []
    for page_num, image in enumerate(images):
        # OCR with Tesseract
        text = pytesseract.image_to_string(image)
        
        # Parse section structure
        parsed = parse_sections(text, page_num)
        sections.extend(parsed)
    
    return sections

def parse_sections(text: str, page: int) -> list:
    """
    Extract section IDs, titles from OCR text
    Regex patterns for "9.10.14.1 Title of Section"
    """
    import re
    pattern = r'(\d+\.\d+\.\d+\.\d+)\s+(.+)'
    matches = re.findall(pattern, text)
    
    return [{
        'id': match[0],
        'title': match[1],
        'page': page
    } for match in matches]
```

---

## Cost Estimates

### Infrastructure (Monthly)
- GCP Compute Engine (e2-micro) VM
- Neon Postgres (managed)
- Cloudflare (DNS + proxy)
- Bandwidth
- **Total Infrastructure**: TBD (depends on usage and plan tiers)

### Services
- Anthropic API (query parsing only, ~1000 queries/month): ~$10-30/month
- Stripe fees: 2.9% + $0.30 per transaction
- Domain + SSL: ~$15/year

### Total Operating Costs
- **Initial**: ~$40-60/month (minimal usage)
- **At 50 users**: ~$60-90/month (includes API costs)
- **At 200 users**: ~$100-150/month

### Break-even Analysis
At $30/month per Pro user:
- **2 users**: $60/month revenue, ~$50/month costs = **Break-even**
- **10 users**: $300/month revenue, ~$70/month costs = **Profitable**
- **50 users**: $1,500/month revenue, ~$90/month costs = **Highly profitable**

**Note:** Costs are ~50% lower than original estimate due to:
- No Neo4j server ($15/month saved)
- ARM instances (t4g vs t3, ~$6/month saved)
- No PDF storage ($5/month saved)
- Synthesis deferred to post-MVP (~$50/month API costs saved initially)

---

## Development Timeline Summary

| Week | Focus | Deliverable |
|------|-------|-------------|
| 1 | Infrastructure | Terraform deployed, GCP + Neon + Cloudflare configured |
| 2 | Data pipeline | OBC scraped, NBC imported, maps loaded into Postgres |
| 3 | Query processing | LLM parser + code resolver working |
| 4 | Search execution | building-code-mcp integration complete |
| 5 | Backend API | Django Ninja endpoints functional |
| 6 | Frontend | HTMX interface complete |
| 7 | Payments | Stripe integration, subscription management |
| 8 | Testing & deploy | Production deployment, monitoring |

**Total**: 8 weeks to MVP

MVP provides:
- ✓ Section search results
- ✓ Section metadata (page, title)
- ✓ Full text for OBC
- ✓ Coordinate references for NBC

---

## Post-MVP Enhancements

### Version 2 Features (Month 3-4)
1. **API access**:
   - Developer API for third-party integrations  
2. **AI Synthesis (Pro tier)**:
   - LLM-generated answers from search results
   - "Ask AI" button separate from simple search
   - Estimated cost: $50-100/month additional API usage

```python
# Future feature - NOT in MVP
@api.post("/search/synthesize", auth=django_auth)
def search_with_synthesis(request, query: str):
    """
    Pro tier only: AI-powered answer synthesis
    
    Takes search results and uses Claude to write a comprehensive answer
    """
    # Check user has Pro subscription
    if request.user.subscription.plan not in ['pro', 'enterprise']:
        return {"error": "Pro subscription required for AI synthesis"}
    
    # Execute normal search
    results = execute_search(...)
    
    # Use Claude to synthesize answer
    synthesis = synthesize_answer(query, results)
    
    return {
        "results": results,
        "ai_answer": synthesis  # LLM-generated summary
    }
```

3. **Historical expansion**: Add pre-2004 codes
   - 1975 OBC (already available)
   - Contact Alek Antoniuk for 1983-1997
   - OCR pipeline for any missing editions


4. **Advanced search filters?**:
   - Filter by building type, part number
   - Boolean operators (AND, OR, NOT)
   - Section range queries

### Version 3 Features (Month 5-6)
1. **Export functionality**: PDF reports of search results
2. **Search history analytics**: Track commonly searched topics
3. **Comparison tool**: Side-by-side code edition comparison

### Future Considerations
1. **More provinces**: BC, AB, QC building codes
2. **Graph database**: Add Neo4j if users request complex relationship queries
3. **Mobile apps**: iOS/Android if web traffic justifies
4. **Compliance checker**: Upload building plans, automated compliance checking

```
### re: Graph Database
The building-code-mcp package already provides:
- Section hierarchies (parent/child relationships)
- Keyword indexing
- Coordinate-based search

For MVP, we only need:
- Time-aware code selection ("which code was in effect in 1993?")
- Keyword validation ("does this query match any known terms?")
- Simple result display

CodeEdition tables handle the year→code mappings. Building-code-mcp handles the search.

Graph databases (Neo4j) would only be needed for:
- Multi-hop reference traversal ("show all dependencies 3 levels deep")
- Complex amendment impact analysis
- Automated compliance checking

**These are not MVP features.** Add graph capabilities later only if users request them.
```

---

## When to Add Neo4j

Add Neo4j graph database ONLY if users request:
- "Show me ALL sections that depend on Section X" (multi-hop traversal)
- "What sections were affected by Amendment Y?" (reverse dependencies)
- "Trace requirement from Part 3 to Part 9" (complex relationship queries)

For MVP, PostgreSQL + building-code-mcp handles all search needs.

---

## Success Metrics

### Technical KPIs
- Search latency < 2 seconds
- 99% uptime
- LLM parsing accuracy > 90%
- Graph query response time < 500ms

### Business KPIs
- Monthly recurring revenue (MRR)
- Customer acquisition cost (CAC)
- Churn rate < 5%
- Net promoter score (NPS)

### User Engagement
- Searches per user per month
- Free-to-paid conversion rate
- Feature adoption (PDF upload, AI synthesis)
- Support ticket volume

---

## Risk Mitigation

### Technical Risks
1. **Neo4j performance**: Monitor query times, add indexes, consider sharding if needed
2. **LLM costs**: Implement caching for common queries, rate limiting
3. **PDF extraction accuracy**: Validate against known sections, provide user feedback mechanism

### Business Risks
1. **Competition**: CanCodes adds historical features → Focus on superior UX, amendment tracking
2. **NRC licensing**: They deny commercial use → Pivot to coordinate-index-only for NBC
3. **Low adoption**: Engineers don't see value → Free tier to prove value, case studies

### Legal Risks
1. **Copyright**: Conservative approach - coordinate index for NBC, full text only for Crown copyright
2. **Liability**: Clear disclaimers, E&O insurance when revenue justifies ($1200-3000/year)
3. **Data accuracy**: Version all data, track sources, allow user corrections

---

## Next Steps

1. **Immediate** (This week):
   - Create Django project skeleton

2. **Week 1**:
   - Start e-Laws scraper development
   - Import building-code-mcp as dependency
   - Design Neo4j schema in detail

3. **Ongoing**:
   - Document data sources and parsing decisions
   - Build automated tests as features develop
   - Track actual vs estimated timeline

4. **Before launch**:
   - Beta test with 5-10 engineers
   - Iterate on UX based on feedback
   - Finalize pricing based on actual costs
   - Set up monitoring (Sentry, GCP Cloud Monitoring)

---

## Contact & Resources

### Key Dependencies
- building-code-mcp: https://github.com/DavidCho1999/Canada_building_code_mcp
- CodeNews.ca: https://www.codenews.ca/OBC/OBC.html (Alek Antoniuk)
- e-Laws: https://www.ontario.ca/laws
- NRC Publications: https://nrc-publications.canada.ca

### Technical Documentation
- Neo4j Cypher Manual: https://neo4j.com/docs/cypher-manual/
- Django Ninja: https://django-ninja.rest-framework.com/
- HTMX: https://htmx.org/docs/
- Anthropic API: https://docs.anthropic.com/

### Community
- Consider open-sourcing the data pipeline (not core business logic)
- Contribute historical parsing improvements back to building-code-mcp
- Engage with r/engineering, Canadian engineering forums for feedback

---

**This plan is a living document. Update as you learn more during implementation.**
