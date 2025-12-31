/**
 * API Client for E2E Demo Application
 */
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

        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, config);

            if (!response.ok) {
                console.error(`API error: ${response.status}`);
                return null;
            }

            return response.json();
        } catch (error) {
            console.error('API fetch error:', error);
            return null;
        }
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

    put(endpoint, data) {
        return this._fetch(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    delete(endpoint) {
        return this._fetch(endpoint, { method: 'DELETE' });
    }
}
