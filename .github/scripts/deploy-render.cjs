const { setTimeout: wait } = require('node:timers/promises');

const pending = new Set([
  'created', 'queued', 'build_in_progress', 'pre_deploy_in_progress', 'update_in_progress',
]);

async function render(path, token, payload) {
  const response = await fetch('https://api.render.com/v1/services/' + path, {
    method: payload ? 'POST' : 'GET',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: payload && JSON.stringify(payload),
    redirect: 'error',
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error('Render API HTTP ' + response.status);
  return response.json();
}

async function deploy({ name, id, url, health }, token, sha) {
  const request = await render(id + '/deploys', token, { commitId: sha });
  if (!/^dep-[a-z0-9]+$/.test(request.id)) throw new Error('Invalid deploy ID');
  console.log(name + ' started ' + request.id);

  const deadline = Date.now() + 22 * 60 * 1000;
  while (Date.now() < deadline) {
    await wait(12000);
    const result = await render(id + '/deploys/' + request.id, token);
    if (result.status === 'live') {
      if (result.commit?.id !== sha) throw new Error('Render deployed a different commit');
      break;
    }
    if (!pending.has(result.status)) throw new Error('Render deploy ended without becoming live');
  }
  if (Date.now() >= deadline) throw new Error('Timed out waiting for Render');

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(url + health, {
        redirect: 'error',
        signal: AbortSignal.timeout(50000),
      });
      if (response.ok) {
        console.log(name + ' live at ' + sha + ' with HTTP ' + response.status);
        return;
      }
    } catch {
      // A free web service may still be waking up.
    }
    await wait(5000);
  }
  throw new Error('Public endpoint failed its health check');
}

async function main() {
  const env = process.env;
  const sha = env.GITHUB_SHA;
  const token = env.RENDER_API_KEY;
  if (!token || !/^[0-9a-f]{40}$/.test(sha) || !env.RENDER_DEPLOY_BRANCH ||
      env.RENDER_DEPLOY_BRANCH !== env.GITHUB_REF_NAME) {
    throw new Error('Check the Render API key, branch and Git commit configuration');
  }

  const services = ['BACKEND', 'WORKER', 'FRONTEND'].map(name => {
    const id = env['RENDER_' + name + '_ID'];
    const url = env['RENDER_' + name + '_URL'];
    if (!/^srv-[a-z0-9]+$/.test(id) || !/^https:\/\/[a-z0-9-]+\.onrender\.com$/.test(url)) {
      throw new Error('Invalid service ID or URL for ' + name);
    }
    return { name, id, url, health: name === 'FRONTEND' ? '/' : '/health' };
  });
  if (new Set(services.map(service => service.id)).size !== services.length) {
    throw new Error('Each component must have its own Render service ID');
  }

  const results = await Promise.allSettled(services.map(service => deploy(service, token, sha)));
  for (const [index, result] of results.entries()) {
    if (result.status === 'rejected') {
      console.error(services[index].name + ' failed: ' + result.reason.message);
      process.exitCode = 1;
    }
  }
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
