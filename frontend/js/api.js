import { CONFIG } from './config.js';
let runtime = { mode: CONFIG.mode, baseUrl: CONFIG.apiBaseUrl, accessToken: '' };
export function getRuntime() { return { ...runtime, accessToken: runtime.accessToken ? '(đang có token)' : '' }; }
export function updateRuntime(next) { runtime = { ...runtime, ...next }; }
export const isDemo = () => runtime.mode === 'demo';
const endpoint = path => runtime.baseUrl.replace(/\/+$/, '').replace(/\/api$/, '') + '/api' + path;
const normalizeAlbum = a => ({ ...a, id: String(a.id ?? a._id) });
const normalizePhoto = p => ({ ...p, id: String(p.id ?? p._id), albumId: p.albumId == null ? null : String(p.albumId), name: p.originalName ?? p.name, status: String(p.status ?? '').toLowerCase(), url: p.originalUrl, progress: p.progress ?? 0 });
async function request(path, options = {}) {
    const headers = { ...options.headers };
    if (options.body) headers['Content-Type'] = 'application/json';
    if (runtime.accessToken) headers.Authorization = `Bearer ${runtime.accessToken}`;
    const res = await fetch(endpoint(path), { ...options, headers });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.message || `API lỗi HTTP ${res.status}`);
    return body;
}
export const remoteApi = {
    me: () => request('/auth/me'),
    async albums() { return (await request('/albums')).albums.map(normalizeAlbum); },
    async images() { return (await request('/photos')).photos.map(normalizePhoto); },
    async createAlbum(body) { return normalizeAlbum((await request('/albums', { method: 'POST', body: JSON.stringify(body) })).album); },
    inviteViewer: (albumId, memberId) => request(`/albums/${encodeURIComponent(albumId)}/members`, {
        method: 'POST', body: JSON.stringify({ memberId })
    }),
    imageStatus: id => request(`/photos/${encodeURIComponent(id)}/status`),
    upload(file, albumId, onProgress = () => {}) {
        return new Promise((resolve, reject) => {
            const form = new FormData(); form.append('albumId', albumId); form.append('image', file);
            const xhr = new XMLHttpRequest(); xhr.open('POST', endpoint('/photos/upload'));
            if (runtime.accessToken) xhr.setRequestHeader('Authorization', `Bearer ${runtime.accessToken}`);
            xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(Math.min(99, Math.round(e.loaded / e.total * 100))); };
            xhr.onload = () => { let body; try { body = JSON.parse(xhr.responseText); } catch { body = {}; }
                if (xhr.status >= 200 && xhr.status < 300) { onProgress(100); resolve(body); }
                else reject(new Error(body.message || `Upload lỗi HTTP ${xhr.status}`)); };
            xhr.onerror = () => reject(new Error('Không kết nối được Backend. Kiểm tra URL, CORS và mạng.'));
            xhr.ontimeout = () => reject(new Error('Hết thời gian chờ; kiểm tra danh sách ảnh trước khi tải lại.'));
            xhr.timeout = 120000; xhr.send(form);
        });
    }
};
