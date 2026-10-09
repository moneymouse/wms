import { formatStorageBytes, storagePhotoRequest, storageRequest } from './storageApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('./safeHeader', () => () => ({ 'x-token': 'storage-user', 'x-time': '123' }));

beforeEach(() => { global.fetch = jest.fn(); });
afterEach(() => { jest.restoreAllMocks(); });

test('storage requests send authenticated filters and encode packing list searches', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { items: [], total: 0 } }) });
    await expect(storageRequest('/packing-lists', { params: { days: 180, page: 2, page_size: 20, q: '装箱 / A' } }))
        .resolves.toEqual({ items: [], total: 0 });
    const [url, options] = global.fetch.mock.calls[0];
    const params = new URL(url, 'http://localhost').searchParams;
    expect(params.get('q')).toBe('装箱 / A');
    expect(params.get('days')).toBe('180');
    expect(params.get('page')).toBe('2');
    expect(options.headers['x-token']).toBe('storage-user');
    expect(options.headers).not.toHaveProperty('Content-Type');
});

test('source deletion sends the warning threshold as JSON with authentication', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { deleted_files: 3 } }) });
    await storageRequest('/intakes/intake-1/photos', { method: 'DELETE', body: { days: 90 } });
    expect(global.fetch).toHaveBeenCalledWith('/api/storage/intakes/intake-1/photos', expect.objectContaining({
        method: 'DELETE', body: '{"days":90}', headers: { 'x-token': 'storage-user', 'x-time': '123', 'Content-Type': 'application/json' },
    }));
});

test('photo files use authenticated blob requests and encode source and photo identifiers', async () => {
    const blob = new Blob(['image'], { type: 'image/png' });
    global.fetch.mockResolvedValue({ ok: true, blob: async () => blob });
    const controller = new AbortController();
    await expect(storagePhotoRequest('intake / 1', 'photo / 1', { signal: controller.signal })).resolves.toBe(blob);
    expect(global.fetch).toHaveBeenCalledWith('/api/storage/intakes/intake%20%2F%201/photos/photo%20%2F%201', {
        signal: controller.signal, headers: { 'x-token': 'storage-user', 'x-time': '123' },
    });
});

test.each([
    [404, { msg: '照片文件不存在' }, '照片文件不存在'],
    [403, { msg: '没有查看权限' }, '没有查看权限'],
    [500, null, '照片加载失败，请重试'],
])('photo errors remain visible for HTTP %s', async (status, result, message) => {
    global.fetch.mockResolvedValue({ ok: false, status, json: async () => { if (!result) throw new Error('invalid json'); return result; } });
    await expect(storagePhotoRequest('intake-1', 'photo-1')).rejects.toThrow(message);
});

test.each([
    [true, 409, '装箱单尚未全部出货'],
    [false, 403, '没有清理权限'],
])('server business errors are rejected even when HTTP succeeds', async (ok, code, msg) => {
    global.fetch.mockResolvedValue({ ok, json: async () => ({ code, msg }) });
    await expect(storageRequest('/summary')).rejects.toThrow(msg);
});

test('invalid server responses report a useful error', async () => {
    global.fetch.mockResolvedValue({ ok: false, json: async () => { throw new Error('not json'); } });
    await expect(storageRequest('/summary')).rejects.toThrow('服务器返回格式错误');
});

test('disk usage remains unknown when statistics could not be read', () => {
    expect(formatStorageBytes(undefined)).toBe('—');
    expect(formatStorageBytes(0)).toBe('0 B');
    expect(formatStorageBytes(1536)).toBe('1.50 KB');
    expect(formatStorageBytes(1048576)).toBe('1.00 MB');
});
