import { fetchShippingConfirmationPdf, shippingConfirmationRequest } from './shippingConfirmationApi';
import { endpoint } from '../config';

let originalFetch;
beforeEach(() => { originalFetch = global.fetch; global.fetch = jest.fn(); localStorage.setItem('jwt', 'test-token'); });
afterEach(() => { global.fetch = originalFetch; localStorage.clear(); });

test('sends versioned JSON updates with the authenticated headers', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 200, data: { uid: 'draft-1', version: 3 } }) });
    await expect(shippingConfirmationRequest('/shipping-confirmation-drafts/draft-1', { method: 'PUT', body: { expected_version: 2, entries: [] } }))
        .resolves.toEqual({ uid: 'draft-1', version: 3 });
    expect(global.fetch).toHaveBeenCalledWith(`${endpoint}/shipping-confirmation-drafts/draft-1`, {
        method: 'PUT', headers: expect.objectContaining({ 'Content-Type': 'application/json', 'x-token': 'test-token' }),
        body: JSON.stringify({ expected_version: 2, entries: [] }),
    });
});

test('exposes conflict status so the dialog can retain unsaved edits', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 409, json: async () => ({ code: 409, msg: '草稿已更新' }) });
    await expect(shippingConfirmationRequest('/shipping-confirmation-drafts/draft-1')).rejects.toMatchObject({ status: 409, message: '草稿已更新' });
});

test('only accepts a nonempty PDF response for the saved version', async () => {
    const pdf = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    global.fetch.mockResolvedValue({ ok: true, headers: { get: () => 'application/pdf' }, blob: async () => pdf });
    await expect(fetchShippingConfirmationPdf('draft-1', 4)).resolves.toBe(pdf);
    expect(global.fetch).toHaveBeenCalledWith(`${endpoint}/shipping-confirmation-drafts/draft-1/pdf`, expect.objectContaining({ body: JSON.stringify({ expected_version: 4 }) }));
    global.fetch.mockResolvedValue({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ code: 400, msg: '箱子已归档' }), blob: jest.fn() });
    await expect(fetchShippingConfirmationPdf('draft-1', 4)).rejects.toThrow('箱子已归档');
    global.fetch.mockResolvedValue({ ok: true, headers: { get: () => 'application/pdf' }, blob: async () => new Blob([]) });
    await expect(fetchShippingConfirmationPdf('draft-1', 4)).rejects.toThrow('出货确认单 PDF 为空');
});
