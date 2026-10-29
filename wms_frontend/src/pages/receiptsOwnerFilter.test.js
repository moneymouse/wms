import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Receipts from './receipts';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.setTimeout(15000);
const payment = { id: 1, number: 'PAY-MINE', partner_type: 'customer', partner_name: '客户A', direction: 'incoming', payment_date: '2026-10-05', amount: '100.00', unallocated_amount: '100.00', status: 'posted', created_by_id: 7, created_by_name: '我' };
const response = (items, page = 1) => ({ ok: true, json: async () => ({ code: 200, data: { items, page, page_size: 20, total: 41 } }) });
function queries() { return global.fetch.mock.calls.map(([url]) => new URL(url, 'http://localhost')).filter(url => url.pathname === '/api/finance/v2/payments').map(url => url.searchParams); }
function latest() { const rows = queries(); return rows[rows.length - 1]; }
function renderPage(roles = ['admin'], entry = '/receipts') {
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, name: 'Admin', roles }))}.s`);
    return render(<MemoryRouter initialEntries={[entry]}><Receipts /></MemoryRouter>);
}
async function selectScope(label) {
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '登记人范围' }));
    fireEvent.click(await screen.findByText(label, { selector: '.ant-select-item-option-content' }));
}
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear();
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(async rawUrl => {
        const url = new URL(rawUrl, 'http://localhost');
        if (url.pathname !== '/api/finance/v2/payments') throw new Error(`Unexpected request: ${rawUrl}`);
        return response([{ ...payment, number: url.searchParams.has('created_by_id') ? 'PAY-MINE' : 'PAY-ALL' }], Number(url.searchParams.get('p')));
    });
});
afterEach(() => jest.restoreAllMocks());

test.each(['admin', 'finance'])('%s initially loads only their registered customer payments', async role => {
    renderPage([role]);
    await screen.findByRole('button', { name: 'PAY-MINE' });
    expect(screen.getByRole('combobox', { name: '登记人范围' })).toBeInTheDocument();
    expect(queries().length).toBeGreaterThan(0);
    queries().forEach(params => { expect(params.get('created_by_id')).toBe('7'); expect(params.get('partner_type')).toBe('customer'); expect(params.has('owner_id')).toBe(false); });
});

test('changing mine/all resets pagination and changing back restores creator filtering', async () => {
    renderPage(); await screen.findByRole('button', { name: 'PAY-MINE' });
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => expect(latest().get('p')).toBe('2'));
    await selectScope('全部收付款'); await screen.findByRole('button', { name: 'PAY-ALL' });
    expect(latest().get('p')).toBe('1'); expect(latest().has('created_by_id')).toBe(false); expect(latest().get('partner_type')).toBe('customer');
    await selectScope('我登记的收付款'); await screen.findByRole('button', { name: 'PAY-MINE' });
    expect(latest().get('created_by_id')).toBe('7'); expect(latest().get('p')).toBe('1');
});

test('salespeople have no all-users selector and request their own records', async () => {
    renderPage(['salesperson']); await screen.findByRole('button', { name: 'PAY-MINE' });
    expect(screen.queryByRole('combobox', { name: '登记人范围' })).not.toBeInTheDocument();
    expect(latest().get('created_by_id')).toBe('7');
    expect(global.fetch.mock.calls.some(([url]) => /work\/workers|receivables|receivable-adjustments/.test(url))).toBe(false);
});

test('a delayed mine response cannot replace the newly selected all scope', async () => {
    let finishMine;
    global.fetch.mockImplementation(rawUrl => new URL(rawUrl, 'http://localhost').searchParams.has('created_by_id')
        ? new Promise(resolve => { finishMine = resolve; }) : Promise.resolve(response([{ ...payment, number: 'PAY-ALL' }])));
    renderPage(); await waitFor(() => expect(finishMine).toBeDefined());
    await selectScope('全部收付款'); await screen.findByRole('button', { name: 'PAY-ALL' });
    await act(async () => finishMine(response([payment])));
    expect(screen.queryByRole('button', { name: 'PAY-MINE' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'PAY-ALL' })).toBeInTheDocument();
});

test('a bookmarked scope, search, direction, status and page restore without resetting on mount', async () => {
    const filters = encodeURIComponent(JSON.stringify({ q: '客户A', direction: 'incoming', status: 'pending' }));
    renderPage(['admin'], `/receipts?receiptScope=all&receiptPaymentFilters=${filters}&receiptPaymentPage=2`);
    await screen.findByRole('button', { name: 'PAY-ALL' });
    expect(screen.getByPlaceholderText('收付款单号 / 往来单位')).toHaveValue('客户A');
    expect(latest().get('q')).toBe('客户A'); expect(latest().get('p')).toBe('2');
    expect(latest().get('status')).toBe('pending'); expect(latest().get('direction')).toBe('incoming');
    expect(latest().has('created_by_id')).toBe(false);
});

test('a salesperson cannot use a bookmarked all scope to remove the current-user filter', async () => {
    renderPage(['salesperson'], '/receipts?receiptScope=all');
    await screen.findByRole('button', { name: 'PAY-MINE' });
    expect(latest().get('created_by_id')).toBe('7');
});

test('the receivable tab restores from a bookmark and refreshes when returning after registration', async () => {
    const payments = global.fetch.getMockImplementation();
    global.fetch.mockImplementation(async url => String(url).includes('/receivables/unregistered-orders')
        ? { ok: true, json: async () => ({ code: 200, data: [{ uid: 'o-1', order_id: '待登记订单', customer_name: '客户A', receivable_amount: 100 }], total: 1 }) }
        : payments(url));
    renderPage(['salesperson'], '/receipts?receiptTab=receivable');
    expect(await screen.findByRole('link', { name: '待登记订单' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '应收款' })).toHaveAttribute('aria-selected', 'true');
    expect(queries()).toHaveLength(0);
    fireEvent.click(screen.getByRole('tab', { name: '收付款记录' }));
    await screen.findByRole('button', { name: 'PAY-MINE' });
    fireEvent.click(screen.getByRole('tab', { name: '应收款' }));
    await waitFor(() => expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('/receivables/unregistered-orders'))).toHaveLength(2));
});
