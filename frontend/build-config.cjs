const { writeFileSync } = require('node:fs');
const { join } = require('node:path');

const variables = {
  apiBaseUrl: 'VITE_API_BASE_URL',
  tenantId: 'VITE_ENTRA_TENANT_ID',
  frontendClientId: 'VITE_ENTRA_CLIENT_ID',
  apiScope: 'VITE_ENTRA_API_SCOPE',
};

const deployment = Object.fromEntries(Object.entries(variables).map(([key, name]) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing frontend build argument: ${name}`);
  return [key, value];
}));

const api = new URL(deployment.apiBaseUrl);
if (api.protocol !== 'https:' || api.username || api.password || api.search || api.hash) {
  throw new Error('VITE_API_BASE_URL must be an HTTPS URL without credentials, query or fragment');
}
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
if (!uuid.test(deployment.tenantId) || !uuid.test(deployment.frontendClientId)) {
  throw new Error('The Entra tenant and Frontend client IDs must be UUIDs');
}
if (!/^api:\/\/[^\s]+\/[^/\s]+$/.test(deployment.apiScope)) {
  throw new Error('Expected a delegated Backend API scope in api://<resource>/<scope> format');
}

writeFileSync(join(__dirname, 'js', 'deployment-config.js'),
  `export const DEPLOYMENT = Object.freeze(${JSON.stringify(deployment, null, 2)});\n`);
