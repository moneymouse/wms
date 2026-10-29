import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import BusinessReceivables from './businessReceivables';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('./financeWorkspace', () => ({ PaymentEditor: ({ initialContext, onSaved, onClose }) => <div role="dialog">
    <output>{JSON.stringify(initialContext)}</output><button onClick={onSaved}>保存登记</button><button onClick={onClose}>关闭登记</button>
</div> }));
const row = { uid: 'order-1', order_id: 'ORDER-1', customer_id: 2, customer_name: '客户甲', billing_weight: '12.000', receivable_amount: '120.00', quoter_name: '业务员甲' };
function Harness() {
    const location = useLocation(); const navigate = useNavigate();
    return <><BusinessReceivables /><output data-testid="url">{location.search}{location.hash}</output>
        <button onClick={() => navigate(-1)}>后退</button></>;
}
function show(filters, entries) {
    return render(<MemoryRouter initialEntries={entries || [`/receipts?receivableFilters=${encodeURIComponent(JSON.stringify(filters || { q: '', p: 1, s: 20 }))}&keep=1#list`]} initialIndex={entries ? entries.length - 1 : 0}><Harness /></MemoryRouter>);
}
beforeEach(() => {
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ code: 200, data: [row], total: 51 }) }));
});
afterEach(() => jest.restoreAllMocks());
test('restores search and pagination from URL and saves a new search without losing hash or unrelated parameters', async () => {
    show({ q: '客户甲', p: 2, s: 20 });
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(screen.getByLabelText('搜索应收款订单')).toHaveValue('客户甲');
    expect(global.fetch.mock.calls[0][0]).toContain('p=2');
    fireEvent.change(screen.getByLabelText('搜索应收款订单'), { target: { value: '新客户' } });
    fireEvent.keyDown(screen.getByLabelText('搜索应收款订单'), { key: 'Enter', code: 'Enter', charCode: 13 });
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => new URL(url, 'http://localhost').searchParams.get('q') === '新客户')).toBe(true));
    const url = new URL(`http://localhost/${screen.getByTestId('url').textContent}`);
    expect(JSON.parse(url.searchParams.get('receivableFilters'))).toEqual({ q: '新客户', p: 1, s: 20 });
    expect(url.searchParams.get('keep')).toBe('1'); expect(url.hash).toBe('#list');
});
test('registration carries customer and reference order without imposing an amount, then refreshes the list', async () => {
    show(); await screen.findByRole('link', { name: 'ORDER-1' });
    fireEvent.click(screen.getByRole('button', { name: '登记收付款' }));
    const context = JSON.parse(screen.getByRole('dialog').querySelector('output').textContent);
    expect(context).toEqual({ customerId: 2, customerName: '客户甲', orderUid: 'order-1', orderNumber: 'ORDER-1' });
    fireEvent.click(screen.getByRole('button', { name: '保存登记' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
});
test('browser back restores prior search and requests it again', async () => {
    show(null, ['/receipts?receivableFilters=%7B%22q%22%3A%22before%22%2C%22p%22%3A1%2C%22s%22%3A20%7D', '/receipts?receivableFilters=%7B%22q%22%3A%22after%22%2C%22p%22%3A2%2C%22s%22%3A20%7D']);
    await screen.findByRole('link', { name: 'ORDER-1' }); fireEvent.click(screen.getByRole('button', { name: '后退' }));
    await waitFor(() => expect(screen.getByLabelText('搜索应收款订单')).toHaveValue('before'));
    expect(global.fetch.mock.calls.at(-1)[0]).toContain('q=before');
});
test('API error is visible and can be retried', async () => {
    global.fetch.mockResolvedValueOnce({ ok: false, json: async () => ({ code: 500, msg: '读取失败' }) });
    show(); await screen.findByText('读取失败'); fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByRole('link', { name: 'ORDER-1' })).toBeInTheDocument();
});
