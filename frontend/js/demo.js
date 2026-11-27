// Demo trong bộ nhớ: làm mới trang sẽ đưa dữ liệu về mẫu ban đầu.
// Không dùng ảnh bên ngoài, giúp hoạt động ngay cả khi offline.
const svg = (a, b, c, label) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="800" height="600" fill="url(#g)"/><circle cx="630" cy="140" r="75" fill="#ffffff" opacity=".45"/><path d="M0 520L225 220L400 470L540 310L800 570V600H0Z" fill="${c}" opacity=".55"/><text x="400" y="555" text-anchor="middle" fill="white" font-family="Arial" font-size="34" font-weight="bold">${label}</text></svg>`)}`;
let albums = [{ id: 'album-1', name: 'Du lịch', description: 'Những chuyến đi đáng nhớ' }, { id: 'album-2', name: 'Thiên nhiên', description: 'Khoảnh khắc ngoài trời' }, { id: 'album-3', name: 'Gia đình', description: 'Kỷ niệm bên người thân' }];
let images = [
    { id: 'img-1', name: 'hoang-hon.jpg', albumId: 'album-1', status: 'completed', createdAt: '2026-11-20T08:00:00Z', thumbnailUrl: svg('#fdc083', '#f08b84', '#5b3c93', 'Sunset') },
    { id: 'img-2', name: 'bien-xanh.jpg', albumId: 'album-1', status: 'completed', createdAt: '2026-11-19T10:15:00Z', thumbnailUrl: svg('#94e6fa', '#398acc', '#176d96', 'Ocean') },
    { id: 'img-3', name: 'rung-thong.jpg', albumId: 'album-2', status: 'completed', createdAt: '2026-11-18T13:20:00Z', thumbnailUrl: svg('#b5e5cc', '#5aaf9d', '#286a65', 'Forest') },
    { id: 'img-4', name: 'nui-doi.jpg', albumId: 'album-2', status: 'completed', createdAt: '2026-11-17T18:00:00Z', thumbnailUrl: svg('#e0d9fd', '#a58ddd', '#7b6ca8', 'Mountains') },
    { id: 'img-5', name: 'anh-dang-xu-ly.jpg', albumId: 'album-3', status: 'processing', createdAt: '2026-11-22T09:30:00Z' },
    { id: 'img-6', name: 'anh-loi.jpg', albumId: null, status: 'failed', createdAt: '2026-11-22T08:30:00Z' }
];
const watchers = new Set();
const emit = () => watchers.forEach(fn => fn());
export const demo = {
    albums: async () => structuredClone(albums), images: async () => structuredClone(images),
    createAlbum: async ({ name, description }) => { const item = { id: crypto.randomUUID(), name, description }; albums.unshift(item); emit(); return item; },
    async addImage(file, albumId, onProgress) {
        const id = crypto.randomUUID(), src = URL.createObjectURL(file);
        const item = { id, name: file.name, albumId: albumId || null, status: 'pending', createdAt: new Date().toISOString(), thumbnailUrl: src };
        images.unshift(item);
        emit();
        for (let v = 0; v <= 100; v += 20) {
            await new Promise(r => setTimeout(r, 110));
            onProgress(Math.min(v, 100));
        }
        item.status = 'processing';
        emit();
        setTimeout(() => { item.status = 'completed'; emit(); }, 2500);
        return item;
    },
    onChange(fn) { watchers.add(fn); return () => watchers.delete(fn); },
    reset() { images = []; albums = []; emit(); }
};
