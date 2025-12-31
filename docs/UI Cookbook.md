# Flask & Tailwind Modern Agent Cookbook (2025 Edition)

**Version:** 1.0.0
**Target Architecture:** Flask (Backend) + Vanilla JS/AJAX (Frontend) + Tailwind CSS
**Auth Strategy:** Reverse Proxy JWT (Backend Validation Only)

---

## 1. Executive Summary

This cookbook dictates the architecture for an AI Agent (e.g., Claude Code) to scaffold a production-grade Flask web application.

**Core Principles:**
1.  **No-Fuss Frontend:** Use **Tailwind CSS** (via standalone CLI) and **Flowbite** for a robust Admin UI without the complexity of a Node.js build chain (Webpack/Vite).
2.  **Stateless Backend:** Flask serves HTML shells; data is loaded via `fetch` (AJAX).
3.  **Security First:** The application relies on a Reverse Proxy (e.g., Nginx, AWS ALB) for SSL termination and Token injection. The Flask app validates JWTs using RS256 and caches public keys.

---

## 2. Technology Stack

* **Backend:** Python 3.12+, Flask 3.x, PyJWT, Cryptography, Flask-SQLAlchemy.
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
│   ├── /auth               # JWT Validation Logic
│   │   ├── __init__.py
│   │   └── middleware.py
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
├── /utils
│   └── key_cache.py        # Public Key Caching
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
PyJWT>=2.8.0
cryptography>=42.0.0
requests>=2.31.0
cachetools>=5.3.3
python-dotenv>=1.0.1
Flask-SQLAlchemy>=3.1.1
```

### Step 2: Configuration & Environment

**`.env`**
```bash
FLASK_APP=run.py
FLASK_DEBUG=1
# JWT Config
JWT_ISSUER=https://auth.yourdomain.com/
JWT_AUDIENCE=my-flask-app
JWKS_URL=https://auth.yourdomain.com/.well-known/jwks.json
```

**`app/config.py`**
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///app.db')

    # JWT Settings
    JWT_ISSUER = os.environ.get('JWT_ISSUER')
    JWT_AUDIENCE = os.environ.get('JWT_AUDIENCE')
    JWKS_URL = os.environ.get('JWKS_URL')
```

### Step 3: Security - JWT Middleware (Cached RS256)

This is the critical security component. It uses `cachetools` to avoid hitting the JWKS endpoint on every request.

**`app/auth/middleware.py`**
```python
from functools import wraps
from flask import request, jsonify, current_app, g
import jwt
from jwt.algorithms import RSAAlgorithm
import requests
import json
from cachetools import TTLCache

# Cache public key for 1 hour to reduce network latency
key_cache = TTLCache(maxsize=5, ttl=3600)

def get_public_key(jwks_url):
    """Fetch and convert JWKS to a usable RSA Public Key"""
    if "public_key" in key_cache:
        return key_cache["public_key"]

    try:
        resp = requests.get(jwks_url, timeout=5)
        resp.raise_for_status()
        jwks = resp.json()

        # In a generic setup, we grab the first key.
        # Production grade: Match 'kid' from token header.
        public_key = RSAAlgorithm.from_jwk(json.dumps(jwks['keys'][0]))
        key_cache["public_key"] = public_key
        return public_key
    except Exception as e:
        current_app.logger.error(f"JWKS Fetch Error: {e}")
        return None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # 1. Extract Token (Authorization: Bearer <token>)
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            # 401 triggers the frontend to redirect to login
            return jsonify({'error': 'Unauthorized', 'message': 'Token missing'}), 401

        try:
            # 2. Get Configuration
            jwks_url = current_app.config['JWKS_URL']
            audience = current_app.config['JWT_AUDIENCE']
            issuer = current_app.config['JWT_ISSUER']

            # 3. Get Key
            pub_key = get_public_key(jwks_url)
            if not pub_key:
                return jsonify({'error': 'System Error', 'message': 'Key validation unavailable'}), 500

            # 4. Validate Claims (Exp, Aud, Iss, Signature)
            payload = jwt.decode(
                token,
                pub_key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options={"verify_signature": True, "verify_exp": True}
            )

            # 5. Inject User Context
            g.user = payload

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Unauthorized', 'message': 'Token expired'}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({'error': 'Unauthorized', 'message': str(e)}), 401

        return f(*args, **kwargs)
    return decorated
```

### Step 4: Admin UI Theme (Tailwind + Flowbite)

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

### Step 5: Frontend Logic (AJAX Wrapper)

Since the Token comes from the Reverse Proxy (usually in a Cookie or Header injected upstream), the browser handles the transport. However, if the Reverse Proxy passes it to the client to hold, we need an interceptor.

**Assuming the Proxy handles the Header, standard `fetch` is fine. If the App must attach the token manually:**

**`app/static/src/api.js`**
```javascript
export class ApiClient {
    constructor(baseUrl = '/api/v1') {
        this.baseUrl = baseUrl;
    }

    async _fetch(endpoint, options = {}) {
        // If your architecture stores the JWT in localStorage, inject it here.
        // const token = localStorage.getItem('jwt');

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        // if (token) headers['Authorization'] = `Bearer ${token}`;

        const config = {
            ...options,
            headers
        };

        const response = await fetch(`${this.baseUrl}${endpoint}`, config);

        if (response.status === 401) {
            console.warn("Session expired or unauthorized");
            // window.location.href = '/login'; // Redirect logic
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

### Step 6: Application Factory

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
