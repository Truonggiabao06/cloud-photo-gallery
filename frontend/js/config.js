import { DEPLOYMENT } from './deployment-config.js';

export const CONFIG = {
    mode: 'demo',
    apiBaseUrl: DEPLOYMENT.apiBaseUrl
        ?? (location.pathname.startsWith('/gallery') ? location.origin + '/api' : 'http://localhost:3000/api'),
    pollIntervalMs: 10000,
    maxFileBytes: 10 * 1024 * 1024,
    allowedTypes: ['image/jpeg', 'image/png', 'image/webp'],
    entra: {
        tenantId: DEPLOYMENT.tenantId ?? '14d5de2b-d212-4175-92d5-156ea5b7c037',
        frontendClientId: DEPLOYMENT.frontendClientId ?? '3430b068-b6f1-4df0-a4d7-c189af8dcd07',
        apiScope: DEPLOYMENT.apiScope ?? 'api://9300ccc1-a0ef-491a-8740-a4c2c6ed4b80/access_as_user',
        redirectUri: DEPLOYMENT.apiBaseUrl ? location.origin + '/' : 'http://localhost:5500/'
    }
};
