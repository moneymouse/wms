import { addExceptionFollowup, exceptionSubmission, fetchExceptionOrderCargos, fetchOrderException, fetchOrderExceptions, registerOrderException, resolveOrderException, searchExceptionOrders } from './orderExceptionApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
const response = (data, status = 200, msg) => ({ ok: status < 400, status, json: async () => ({ code: status, data, msg }) });
beforeEach(() => { global.fetch = jest.fn(); localStorage.setItem('jwt', 'actor-token'); });
afterEach(() => { localStorage.clear(); jest.restoreAllMocks(); });

test('exception queries encode the explicit scope and preserve abort/auth headers', async () => {
    global.fetch.mockResolvedValue(response({ items: [], total: 0 }));
    const controller = new AbortController();
    await fetchOrderExceptions({ page: 2, pageSize: 20, status: 'resolved', salesmanId: 8, signal: controller.signal });
    expect(global.fetch).toHaveBeenCalledWith('/api/order-exceptions?page=2&page_size=20&status=resolved&salesman_id=8',
        expect.objectContaining({ method: 'GET', signal: controller.signal, headers: expect.objectContaining({ 'x-token': 'actor-token' }) }));
});

test('ordinary salesperson query leaves owner enforcement to the backend', async () => {
    global.fetch.mockResolvedValue(response({ items: [] }));
    await fetchOrderExceptions();
    expect(global.fetch.mock.calls[0][0]).toBe('/api/order-exceptions?page=1&page_size=20&status=open');
});

test('all mutations send the caller stable event key and exact order/package context', async () => {
    global.fetch.mockResolvedValue(response({ uid: 'ex-1' }));
    const body = { order_uid: 'o-1', cargo_uid: 'c-1', reason: '包装破损', event_key: 'stable-key' };
    await registerOrderException(body);
    await addExceptionFollowup('ex/1', { note: '已联系客户', event_key: 'follow-key' });
    await resolveOrderException('ex/1', { event_key: 'resolve-key' });
    expect(global.fetch.mock.calls.map(([url]) => url)).toEqual(['/api/order-exceptions', '/api/order-exceptions/ex%2F1/followups', '/api/order-exceptions/ex%2F1/resolve']);
    expect(global.fetch.mock.calls.map(([, options]) => JSON.parse(options.body))).toEqual([body, { note: '已联系客户', event_key: 'follow-key' }, { event_key: 'resolve-key' }]);
    for (const [, options] of global.fetch.mock.calls) expect(options).toMatchObject({ method: 'POST', headers: { 'Content-Type': 'application/json', 'x-token': 'actor-token' } });
});

test.each([403, 404, 409, 500])('HTTP %s is visible and never retries with broader access', async status => {
    global.fetch.mockResolvedValue(response(null, status, '不能读取该异常'));
    await expect(fetchOrderException('other-case')).rejects.toMatchObject({ status, message: '不能读取该异常' });
    expect(global.fetch).toHaveBeenCalledTimes(1);
});

test('order search uses the existing order API response shape', async () => {
    global.fetch.mockResolvedValue(response([{ uid: 'o-1', order_id: 'ORDER-1' }]));
    await expect(searchExceptionOrders('原单号 A')).resolves.toEqual([{ uid: 'o-1', order_id: 'ORDER-1' }]);
    expect(global.fetch.mock.calls[0][0]).toBe('/api/orders?q=%E5%8E%9F%E5%8D%95%E5%8F%B7+A&p=1&s=20');
});

test('an uncertain submission retains its key until the user changes the payload', () => {
    const ref = { current: null };
    const first = exceptionSubmission(ref, { note: '已联系客户' });
    expect(first.event_key).toMatch(/^[a-f0-9-]{36}$/);
    expect(exceptionSubmission(ref, { note: '已联系客户' })).toEqual(first);
    expect(exceptionSubmission(ref, { note: '客户已补资料' }).event_key).not.toBe(first.event_key);
});

test('local parcels remain selectable when the existing endpoint live tracking lookup fails', async () => {
    global.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 500, msg: '物流查询失败', data: [{ uid: 'cargo-1', transfer_id: 'ORIGINAL-1' }] }) });
    await expect(fetchExceptionOrderCargos('order-1')).resolves.toEqual([{ uid: 'cargo-1', transfer_id: 'ORIGINAL-1' }]);
    await expect(fetchOrderException('exception-1')).rejects.toThrow('物流查询失败');
});

test.each([403, 500])('HTTP %s never exposes partial parcel data as a successful lookup', async status => {
    global.fetch.mockResolvedValue(response([{ uid: 'cargo-1' }], status, '不能读取包裹'));
    await expect(fetchExceptionOrderCargos('order-1')).rejects.toMatchObject({ status, message: '不能读取包裹' });
    expect(global.fetch).toHaveBeenCalledTimes(1);
});
