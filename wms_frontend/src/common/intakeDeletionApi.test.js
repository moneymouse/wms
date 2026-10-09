import { intakeRequest } from './intakeApi';

jest.mock('./safeHeader', () => () => ({ 'x-token': 'test-token' }));

const originalFetch = global.fetch;
beforeEach(() => { global.fetch = jest.fn(); });
afterEach(() => { jest.restoreAllMocks(); global.fetch = originalFetch; });

test('deletion sends the displayed version as authenticated JSON', async () => {
    const data = { deleted: true, photo_cleanup_pending: false };
    jest.spyOn(global, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
    await expect(intakeRequest('/source', { method: 'DELETE', body: { version: 3 } })).resolves.toEqual(data);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/intakes/source'), expect.objectContaining({
        method: 'DELETE', body: '{"version":3}', headers: { 'x-token': 'test-token', 'Content-Type': 'application/json' },
    }));
});

test('cleanup failures retain HTTP status and retry metadata', async () => {
    const data = { deleted: true, photo_cleanup_pending: true };
    jest.spyOn(global, 'fetch').mockResolvedValue({ ok: false, status: 503, json: async () => ({ code: 503, msg: '请重试删除', data }) });
    await expect(intakeRequest('/source', { method: 'DELETE', body: { version: 3 } })).rejects.toMatchObject({
        message: '请重试删除', status: 503, data,
    });
});

test('conflicts retain their status without claiming deletion happened', async () => {
    jest.spyOn(global, 'fetch').mockResolvedValue({ ok: false, status: 409, json: async () => ({ code: 409, msg: '版本已更新' }) });
    await expect(intakeRequest('/source', { method: 'DELETE', body: { version: 3 } })).rejects.toMatchObject({
        message: '版本已更新', status: 409,
    });
});
