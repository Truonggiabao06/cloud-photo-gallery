import { CONFIG } from './config.js';
import { remoteApi, isDemo, updateRuntime, getRuntime } from './api.js';
import { demo } from './demo.js';
const $ = (s) => document.querySelector(s);
const state = { images: [], albums: [], view: 'photos', albumId: null, search: '', filter: 'all', busy: false, polling: false };
const labels = { completed: 'Hoàn thành', processing: 'Đang xử lý', pending: 'Đang chờ', failed: 'Thất bại' };
const escapeHTML = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeImageUrl = (url) => { try {
    if (!url) return '';
    const u = new URL(url, location.href);
    return ['https:', 'http:', 'blob:', 'data:'].includes(u.protocol) ? u.href : '';
}
catch {
    return '';
} };
const date = (s) => s ? new Date(s).toLocaleDateString('vi-VN') : '—';
const statusHTML = (s) => `<span class="status ${escapeHTML(s)}">${labels[s] || escapeHTML(s || 'Không rõ')}</span>`;
const toast = (msg, type = '') => { const d = document.createElement('div'); d.className = `toast ${type}`; d.textContent = msg; $('#toastArea').append(d); setTimeout(() => d.remove(), 4500); };
const show = (id) => document.getElementById(id).showModal();
const close = (id) => document.getElementById(id).close();
const api = () => isDemo() ? demo : remoteApi;
async function refresh(silent = false) {
    try {
        const [albums, images] = await Promise.all([api().albums(), api().images()]);
        state.albums = albums;
        state.images = images;
        render();
    }
    catch (e) {
        if (!silent)
            toast(`Không tải được dữ liệu: ${e.message}`, 'error');
    }
}
function stat() { const count = s => state.images.filter(x => x.status === s).length; $('#statImages').textContent = state.images.length; $('#statAlbums').textContent = state.albums.length; $('#statPending').textContent = count('pending') + count('processing'); $('#statComplete').textContent = count('completed'); }
function empty(title, sub) { return `<div class="empty"><div class="emoji">▧</div><h3>${escapeHTML(title)}</h3><p>${escapeHTML(sub)}</p></div>`; }
function imageCard(im) { const img = safeImageUrl(im.thumbnailUrl || im.url || ''); return `<button class="photo-card" data-image-id="${escapeHTML(im.id)}"><div class="thumb">${img ? `<img src="${escapeHTML(img)}" alt="${escapeHTML(im.name || 'Ảnh')}" loading="lazy">` : '<div class="placeholder">▧</div>'}</div><div class="photo-meta"><div><span class="name" title="${escapeHTML(im.name || '')}">${escapeHTML(im.name || 'Không tên')}</span><small>${date(im.createdAt)}</small></div>${statusHTML(im.status)}</div></button>`; }
function imageList(arr) { return arr.length ? `<div class="photo-grid">${arr.map(imageCard).join('')}</div>` : empty('Chưa có ảnh phù hợp', 'Hãy tải ảnh mới lên hoặc thử từ khóa khác.'); }
function filterImages() { return state.images.filter(im => (!state.albumId || im.albumId === state.albumId) && (state.filter === 'all' || im.status === state.filter) && (im.name || '').toLowerCase().includes(state.search.toLowerCase())); }
function render() {
    stat();
    const onAlbum = state.view === 'albums', onJobs = state.view === 'jobs', single = !!state.albumId;
    let title = onAlbum ? 'Album' : onJobs ? 'Trạng thái xử lý' : single ? (state.albums.find(x => x.id === state.albumId)?.name || 'Album') : 'Tất cả ảnh';
    $('#pageTitle').textContent = title;
    $('#breadcrumbCurrent').textContent = title;
    $('#pageSubtitle').textContent = onAlbum ? 'Sắp xếp ảnh theo các bộ sưu tập.' : onJobs ? 'Theo dõi quá trình tạo thumbnail bất đồng bộ.' : 'Lưu giữ và quản lý những khoảnh khắc của bạn.';
    document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === state.view));
    $('#statusFilter').style.display = onAlbum ? 'none' : '';
    $('#newAlbumBtn').style.display = onJobs ? 'none' : '';
    $('#uploadBtn').style.display = onJobs ? 'none' : '';
    const q = state.search.toLowerCase();
    if (onAlbum) {
        const found = state.albums.filter(x => (x.name || '').toLowerCase().includes(q));
        $('#content').innerHTML = found.length ? `<div class="album-grid">${found.map(a => `<article class="album-card" tabindex="0" role="button" data-album-id="${escapeHTML(a.id)}"><div class="album-cover">▤</div><div class="album-info"><strong>${escapeHTML(a.name)}</strong><p>${state.images.filter(im => im.albumId === a.id).length} ảnh · ${escapeHTML(a.description || 'Chưa có mô tả')}</p></div></article>`).join('')}</div>` : empty('Chưa có album', 'Nhấn “Tạo album” để thêm bộ sưu tập.');
    }
    else if (onJobs) {
        const imgs = filterImages();
        $('#content').innerHTML = imgs.length ? `<div class="jobs-table"><table><thead><tr><th>Tên ảnh</th><th>Job / Image ID</th><th>Trạng thái</th><th>Tiến độ xử lý</th><th>Ngày tạo</th></tr></thead><tbody>${imgs.map(im => `<tr><td>${escapeHTML(im.name)}</td><td class="mono">${escapeHTML(im.id)}</td><td>${statusHTML(im.status)}</td><td>${escapeHTML(im.progress ?? (im.status === 'completed' ? 100 : 0))}%</td><td>${date(im.createdAt)}</td></tr>`).join('')}</tbody></table></div>` : empty('Không có job phù hợp', 'Chưa có tiến trình xử lý ảnh.');
    }
    else
        $('#content').innerHTML = `${single ? '<button class="back-btn" id="backAlbums">← Quay lại Album</button>' : ''}${imageList(filterImages())}`;
    $('#modeChip').textContent = isDemo() ? '● DEMO MODE' : '● API MODE';
    $('#modeChip').classList.toggle('api', !isDemo());
}
function navigate(view, albumId = null) { state.view = view; state.albumId = albumId; state.search = ''; state.filter = 'all'; $('#searchInput').value = ''; $('#statusFilter').value = 'all'; $('#sidebar').classList.remove('open'); render(); }
function detail(id) {
    const im = state.images.find(x => String(x.id) === String(id));
    if (!im)
        return;
    const image = safeImageUrl(im.thumbnailUrl || im.url || '');
    $('#detailTitle').textContent = im.name || 'Chi tiết ảnh';
    $('#detailPreview').innerHTML = image ? `<img src="${escapeHTML(image)}" alt="${escapeHTML(im.name)}">` : '<span style="font-size:50px;color:#90a0b5">▧</span>';
    $('#detailInfo').innerHTML = `<p><strong>Tên file</strong>${escapeHTML(im.name)}</p><p><strong>Trạng thái</strong>${statusHTML(im.status)}</p><p><strong>Album</strong>${escapeHTML(state.albums.find(a => a.id === im.albumId)?.name || 'Chưa phân loại')}</p><p><strong>Ngày tạo</strong>${date(im.createdAt)}</p><p><strong>ID</strong><span class="mono">${escapeHTML(im.id)}</span></p>`;
    show('detailDialog');
}
function prepareUpload() { const select = $('#uploadAlbum'); select.replaceChildren(new Option(isDemo() ? 'Không chọn album' : 'Chọn album (bắt buộc)', '')); state.albums.forEach(a => select.add(new Option(a.name, a.id))); $('#fileInput').value = ''; $('#fileList').replaceChildren(); $('#uploadProgressArea').hidden = true; $('#startUploadBtn').disabled = false; show('uploadDialog'); }
function validFiles(files) { for (const f of files) {
    if (!CONFIG.allowedTypes.includes(f.type))
        throw new Error(`Định dạng không hỗ trợ: ${f.name}`);
    if (f.size > CONFIG.maxFileBytes)
        throw new Error(`Ảnh vượt quá 10 MB: ${f.name}`);
} return files; }
async function uploadFiles(e) {
    e.preventDefault();
    if (state.busy)
        return;
    const files = Array.from($('#fileInput').files);
    if (!files.length)
        return toast('Hãy chọn ít nhất một ảnh.', 'error');
    try {
        validFiles(files);
    }
    catch (err) {
        return toast(err.message, 'error');
    }
    if (!isDemo() && !$('#uploadAlbum').value) return toast('Hãy tạo và chọn album trước khi tải ảnh.', 'error');
    state.busy = true;
    $('#startUploadBtn').disabled = true;
    $('#uploadProgressArea').hidden = false;
    const albumId = $('#uploadAlbum').value || null;
    try {
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const update = (p) => { const percent = Math.round(((i + p / 100) / files.length) * 100); $('#uploadProgressPct').textContent = `${percent}%`; $('#uploadProgressBar').style.width = `${percent}%`; $('#uploadProgressLabel').textContent = `Đang tải ${i + 1}/${files.length}: ${f.name}`; };
            update(0);
            if (isDemo())
                await demo.addImage(f, albumId, update);
            else {
                const result = await remoteApi.upload(f, albumId, update);
                if (!result.queue?.published) toast('Ảnh đã lưu nhưng chưa được đưa vào hàng đợi xử lý.', 'error');
            }
            update(100);
        }
        toast('Đã tải ảnh lên. Ảnh có thể cần thời gian để xử lý thumbnail.', 'success');
        await refresh();
        close('uploadDialog');
        navigate('photos');
    }
    catch (err) {
        toast(`Upload thất bại: ${err.message}`, 'error');
        await refresh(true);
    }
    finally {
        state.busy = false;
        $('#startUploadBtn').disabled = false;
    }
}
async function createAlbum(e) { e.preventDefault(); const name = $('#albumName').value.trim(), description = $('#albumDesc').value.trim(); if (!name)
    return; try {
    await api().createAlbum({ name, description });
    close('albumDialog');
    $('#albumForm').reset();
    toast('Đã tạo album', 'success');
    await refresh();
    navigate('albums');
}
catch (err) {
    toast(`Tạo album lỗi: ${err.message}`, 'error');
} }
function settings() { const r = getRuntime(); $('#settingMode').value = r.mode; $('#settingApiUrl').value = r.baseUrl; $('#settingToken').value = ''; show('settingsDialog'); }
async function saveSettings(e) { e.preventDefault(); const mode = $('#settingMode').value, baseUrl = $('#settingApiUrl').value.trim(); if (mode === 'api' && !/^https?:\/\//i.test(baseUrl))
    return toast('API URL phải bắt đầu bằng http:// hoặc https://', 'error'); updateRuntime({ mode, baseUrl, accessToken: $('#settingToken').value.trim().replace(/^Bearer\s+/i, '') }); state.images = []; state.albums = []; close('settingsDialog'); toast(mode === 'api' ? 'Đã chuyển sang API mode' : 'Đã chuyển sang Demo mode'); navigate('photos'); await refresh(); }
function init() {
    document.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => { if (state.busy && el.dataset.close === 'uploadDialog')
        return; close(el.dataset.close); }));
    document.querySelectorAll('dialog').forEach(d => d.addEventListener('cancel', e => { if (state.busy && d.id === 'uploadDialog')
        e.preventDefault(); }));
    document.querySelectorAll('.nav-item').forEach(b => b.addEventListener('click', () => navigate(b.dataset.view)));
    $('#menuBtn').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
    $('#newAlbumBtn').addEventListener('click', () => show('albumDialog'));
    $('#uploadBtn').addEventListener('click', prepareUpload);
    $('#settingsBtn').addEventListener('click', settings);
    $('#uploadForm').addEventListener('submit', uploadFiles);
    $('#albumForm').addEventListener('submit', createAlbum);
    $('#settingsForm').addEventListener('submit', saveSettings);
    $('#fileInput').addEventListener('change', () => { const items = Array.from($('#fileInput').files); $('#fileList').replaceChildren(...items.map(f => { const d = document.createElement('div'); d.textContent = `▧ ${f.name} (${(f.size / 1024 / 1024).toFixed(2)} MB)`; return d; })); });
    $('#searchInput').addEventListener('input', e => { state.search = e.target.value; render(); });
    $('#statusFilter').addEventListener('change', e => { state.filter = e.target.value; render(); });
    $('#content').addEventListener('click', e => { const a = e.target.closest('[data-album-id]'), i = e.target.closest('[data-image-id]'); if (a)
        navigate('photos', a.dataset.albumId); if (i)
        detail(i.dataset.imageId); if (e.target.closest('#backAlbums'))
        navigate('albums'); });
    $('#content').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('[data-album-id]'))
        navigate('photos', e.target.dataset.albumId); });
    demo.onChange(() => { if (isDemo())
        refresh(true); });
    setInterval(async () => { if (!isDemo() && !state.polling && !state.busy) {
        state.polling = true;
        try {
            await refresh(true);
        }
        finally {
            state.polling = false;
        }
    } }, CONFIG.pollIntervalMs);
    refresh();
}
init();
import('./auth.js').then(({ loginMicrosoft }) => {
    const btn = document.createElement('button');

    btn.id = 'microsoftLoginBtn';
    btn.textContent = 'Đăng nhập Microsoft';

    btn.style.cssText = `
        background: #4268df;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px;
        margin: 10px 0;
        width: 100%;
        cursor: pointer;
        font-weight: 600;
    `;

    document.getElementById('settingsBtn').before(btn);

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Đang đăng nhập...';

        try {
            const account = await loginMicrosoft();

            state.images = [];
            state.albums = [];

            btn.textContent = 'Đã đăng nhập';

            navigate('photos');
            await refresh();

            toast(
                'Đăng nhập thành công: ' + account.name,
                'success'
            );

        } catch (error) {
            btn.textContent = 'Đăng nhập Microsoft';
            toast('Lỗi đăng nhập: ' + error.message, 'error');
            console.error(error);
        } finally {
            btn.disabled = false;
        }
    });
}).catch(error => {
    console.error('MSAL initialization error:', error);
});
