# Flask & Tailwind Modern Agent Cookbook (2025 Edition)

**Version:** 1.0.0
**Target Architecture:** Flask (Backend) + Vanilla JS/AJAX (Frontend) + Tailwind CSS

---

## 1. Executive Summary

This cookbook dictates the architecture for an AI Agent (e.g., Claude Code) to scaffold a production-grade Flask web application.

**Core Principles:**
1.  **No-Fuss Frontend:** Use **Tailwind CSS** (via standalone CLI) and **Flowbite** for a robust Admin UI without the complexity of a Node.js build chain (Webpack/Vite).
2.  **Stateless Backend:** Flask serves HTML shells; data is loaded via `fetch` (AJAX).

---

## 2. Technology Stack

* **Backend:** Python 3.12+, Flask 3.x, Flask-SQLAlchemy.
* **Frontend Styling:** Tailwind CSS (CLI), Flowbite (Component Library).
* **Frontend Logic:** Vanilla ES6+ JavaScript (Modules).
* **Database:** SQLite (Dev) / PostgreSQL (Prod).

---

## 3. Project Directory Structure

The agent must enforce this modular structure:

```text
/project_root
├── /app
│   ├── /api                # JSON Endpoints
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── /static
│   │   ├── /dist           # Generated output (Do not edit)
│   │   │   └── output.css
│   │   ├── /src
│   │   │   ├── input.css   # Tailwind directives
│   │   │   └── api.js      # AJAX Wrapper
│   │   └── /js             # UI Interaction scripts
│   ├── /templates
│   │   ├── /includes       # Navbar, Sidebar
│   │   ├── /layouts        # Base HTML skeletons
│   │   └── index.html
│   ├── __init__.py         # App Factory
│   ├── config.py           # Env Config
│   └── models.py           # DB Models
├── .env                    # Secrets
├── tailwind.config.js      # Tailwind Config
├── requirements.txt        # Python Deps
└── run.py                  # Entry Point
```

---

## 4. Implementation Steps

### Step 1: Dependency Management

**`requirements.txt`**
```text
Flask>=3.0.2
python-dotenv>=1.0.1
Flask-SQLAlchemy>=3.1.1
```

### Step 2: Configuration & Environment

**`.env`**
```bash
FLASK_APP=run.py
FLASK_DEBUG=1
```

**`app/config.py`**
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
```

### Step 3: Admin UI Theme (Tailwind + Flowbite)

We use the standalone Tailwind CLI to avoid `node_modules` bloat.

**1. Setup Command (Run once):**
```bash
# Download tailwind cli for your OS
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
chmod +x tailwindcss-linux-x64
mv tailwindcss-linux-x64 tailwindcss
```

**2. `tailwind.config.js`**
```javascript
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/**/*.js"
  ],
  theme: {
    extend: {
      colors: {
        primary: {"50":"#eff6ff","100":"#dbeafe","200":"#bfdbfe","300":"#93c5fd","400":"#60a5fa","500":"#3b82f6","600":"#2563eb","700":"#1d4ed8","800":"#1e40af","900":"#1e3a8a"}
      }
    },
  },
  plugins: [
    // We will load Flowbite via CDN for simplicity in this specific "lightweight" recipe,
    // or via npm if a build step is strictly required.
    // For this cookbook, we assume CDN for Flowbite JS, but Tailwind for CSS.
  ],
}
```

**3. Base Layout (`app/templates/layouts/base.html`)**
*Use the Flowbite "Sidebar Layout" pattern.*

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Admin Dashboard{% endblock %}</title>
    <link href="{{ url_for('static', filename='dist/output.css') }}" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.1/flowbite.min.css" rel="stylesheet" />
</head>
<body class="bg-gray-50 dark:bg-gray-900">

    {% include 'includes/navbar.html' %}

    {% include 'includes/sidebar.html' %}

    <div class="p-4 sm:ml-64 mt-14">
        {% block content %}{% endblock %}
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.1/flowbite.min.js"></script>
    <script type="module" src="{{ url_for('static', filename='src/api.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

### Step 4: Frontend Logic (AJAX Wrapper)

**`app/static/src/api.js`**
```javascript
export class ApiClient {
    constructor(baseUrl = '/api/v1') {
        this.baseUrl = baseUrl;
    }

    async _fetch(endpoint, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        const config = {
            ...options,
            headers
        };

        const response = await fetch(`${this.baseUrl}${endpoint}`, config);

        if (!response.ok) {
            console.error(`API error: ${response.status}`);
            return null;
        }

        return response.json();
    }

    get(endpoint) {
        return this._fetch(endpoint, { method: 'GET' });
    }

    post(endpoint, data) {
        return this._fetch(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
}
```

### Step 5: Application Factory

**`app/__init__.py`**
```python
from flask import Flask
from .config import Config

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    # db.init_app(app)

    # Register Blueprints
    from app.api.routes import api_bp
    app.register_blueprint(api_bp)

    from app.web.routes import web_bp # Serve HTML
    app.register_blueprint(web_bp)

    return app
```

---

## 5. Development Command Reference

**1. Start CSS Watcher:**
```bash
./tailwindcss -i ./app/static/src/input.css -o ./app/static/dist/output.css --watch
```

**2. Start Flask Server:**
```bash
flask run --debug
```
