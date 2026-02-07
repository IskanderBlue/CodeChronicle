# CodeChronicle

Historical Canadian Building Code Search - Find code requirements for buildings constructed at specific dates.

## Quick Start

```bash
# Clone and enter directory
cd CodeChronicle

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -e ".[dev]"

# Create .env from template
copy .env.example .env
# Edit .env with your API keys

# Run migrations
python manage.py migrate
```

If you prefer to use PostgreSQL locally:

```bash
# Local Development with Docker (PostgreSQL)

# Start the database
docker-compose up -d

# In your .env file
DATABASE_URL=postgres://postgres:postgres@localhost:5432/code_chronicle
```

Finally:

```bash
# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

## Project Structure

```

CodeChronicle/
├── code_chronicle/     # Django project settings
├── api/                # API endpoints (Django Ninja)
├── core/               # Models, middleware, frontend views
├── config/             # Code metadata and map loading
├── templates/          # HTML templates
└── prompts/            # Planning notes (not deployed)

```

## Environment Variables

See `.env.example` for required configuration.

## License

MIT
