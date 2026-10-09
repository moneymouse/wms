import { downloadReconciliationTemplate, reconcileBatch, reconciliationRequest, uploadReconciliation } from './supplierReconciliationApi';
import { endpoint } from '../config';

let originalFetch;
beforeEach(() => { originalFetch = global.fetch; global.fetch = jest.fn(); localStorage.setItem('jwt', 'clerk-token'); });
afterEach(() => { global.fetch = originalFetch; localStorage.clear(); });

test('lists batches with authenticated headers and only populated filters', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { items: [], total: 0 } }) });
    const controller = new AbortController();
    await expect(reconciliationRequest('/batches', { params: { p: 2, row_status: undefined }, signal: controller.signal })).resolves.toEqual({ items: [], total: 0 });
    expect(global.fetch).toHaveBeenCalledWith(`${endpoint}/supplier-reconciliation/batches?p=2`, expect.objectContaining({ headers: expect.objectContaining({ 'x-token': 'clerk-token' }), signal: controller.signal }));
});

test('uploads multipart data without overriding the browser boundary', async () => {
    const file = new File(['xlsx'], '明细.xlsx');
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { batch: { id: 2 }, rows: { items: [] } } }) });
    await uploadReconciliation({ file, vendorId: 3, period: '2026-10' });
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe(`${endpoint}/supplier-reconciliation/batches`);
    expect(options.method).toBe('POST');
    expect(options.headers['x-token']).toBe('clerk-token');
    expect(options.headers['Content-Type']).toBeUndefined();
    expect(options.body.get('file')).toBe(file);
    expect(options.body.get('vendor_id')).toBe('3');
    expect(options.body.get('period')).toBe('2026-10');
});

test('preserves server validation errors and status for failed uploads', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 400, json: async () => ({ code: 400, msg: '缺少必填列：最终费用(元)' }) });
    await expect(uploadReconciliation({ file: new File(['x'], '账单.xlsx'), vendorId: 2, period: '2026-10' })).rejects.toMatchObject({ status: 400, message: '缺少必填列：最终费用(元)' });
});

test('rechecks unresolved exceptions using the current batch version', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ code: 200, data: { batch: { id: 2, version: 4 }, rows: { items: [] } } }) });
    await expect(reconcileBatch(2, 3)).resolves.toMatchObject({ batch: { version: 4 } });
    expect(global.fetch).toHaveBeenCalledWith(`${endpoint}/supplier-reconciliation/batches/2/reconcile`, {
        method: 'POST', headers: expect.objectContaining({ 'x-token': 'clerk-token', 'Content-Type': 'application/json' }), body: JSON.stringify({ version: 3 }),
    });
});

test('downloads the template with authentication and rejects empty or failed responses', async () => {
    const blob = new Blob(['xlsx']);
    global.fetch.mockResolvedValue({ ok: true, headers: { get: () => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, blob: async () => blob });
    await expect(downloadReconciliationTemplate()).resolves.toBe(blob);
    expect(global.fetch).toHaveBeenCalledWith(`${endpoint}/supplier-reconciliation/template`, expect.objectContaining({ headers: expect.objectContaining({ 'x-token': 'clerk-token' }) }));
    global.fetch.mockResolvedValue({ ok: true, headers: { get: () => 'application/octet-stream' }, blob: async () => new Blob([]) });
    await expect(downloadReconciliationTemplate()).rejects.toThrow('对账模板为空');
    global.fetch.mockResolvedValue({ ok: false, status: 403, headers: { get: () => 'application/json' }, json: async () => ({ code: 403, msg: '没有权限下载模板' }) });
    await expect(downloadReconciliationTemplate()).rejects.toThrow('没有权限下载模板');
});
