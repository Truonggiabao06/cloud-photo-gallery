import { updateRuntime, remoteApi } from './api.js';
import { CONFIG } from './config.js';

const client = new msal.PublicClientApplication({
    auth: {
        clientId: CONFIG.entra.frontendClientId,
        authority: `https://login.microsoftonline.com/${CONFIG.entra.tenantId}`,
        redirectUri: CONFIG.entra.redirectUri
    },
    cache: {
        cacheLocation: 'memoryStorage'
    }
});

const scopes = [CONFIG.entra.apiScope];

const ready = client.initialize();

export async function loginMicrosoft() {
    await ready;

    const result = await client.loginPopup({ scopes });
    client.setActiveAccount(result.account);

    const token = await client.acquireTokenSilent({
        account: result.account,
        scopes
    });

    updateRuntime({
        mode: 'api',
        baseUrl: CONFIG.apiBaseUrl,
        accessToken: token.accessToken
    });

    try {
        await remoteApi.me();
        return result.account;
    } catch (error) {
        updateRuntime({
            mode: 'demo',
            accessToken: ''
        });
        throw error;
    }
}