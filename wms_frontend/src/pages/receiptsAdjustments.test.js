import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { LegacyReceiptHistory } from './receipts';
import { printReceipt } from '../common/receiptApi';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../common/receiptApi', () => ({ ...jest.requireActual('../common/receiptApi'), printReceipt: jest.fn() }));
jest.setTimeout(15000);
const receipt = { id: 9, receipt_no: 'RC-ADJUSTMENT-REJECTED', customer_name: '客户A', receipt_date: '2026-09-16', total_amount: 30, status: 'rejected', settlement_status: 'unsettled', remark: '旧补收说明', review_remark: '金额需核对', items: [{ order_uid: 'old-order', order_id: 'OLD-ORDER', amount: 30, adjustment_id: 3 }] };
const response = (data, extra = {}) => ({ ok: true, json: async () => ({ code: 200, data, ...extra }) });
function requests(path) { return global.fetch.mock.calls.filter(([url]) => new URL(url, 'http://localhost').pathname === path); }
function mockApi() {
    global.fetch = jest.fn(async rawUrl => {
        const url = new URL(rawUrl, 'http://localhost');
        if (url.pathname === '/api/receipts') return response([receipt], { total: 41, page: Number(url.searchParams.get('p')), page_size: 20 });
        if (url.pathname === '/api/receipts/9') return response(receipt);
        if (url.pathname === '/api/receipts/9/history') return response({ items: [], total: 0, history_complete: false, notice: '旧版记录可能存在缺口' });
        throw new Error(`Unexpected request: ${rawUrl}`);
    });
}
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear(); printReceipt.mockClear();
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }))}.s`);
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    mockApi();
});
afterEach(() => jest.restoreAllMocks());

test.each(['pending', 'approved', 'rejected'])('legacy %s records are read-only and cannot copy or create adjustment collections', async status => {
    global.fetch.mockImplementation(async rawUrl => new URL(rawUrl, 'http://localhost').pathname === '/api/receipts/9'
        ? response({ ...receipt, status }) : response([{ ...receipt, status }], { total: 1 }));
    render(<LegacyReceiptHistory />);
    fireEvent.click(await screen.findByRole('button', { name: receipt.receipt_no }));
    const drawer = within(await screen.findByRole('dialog', { name: receipt.receipt_no }));
    expect(await drawer.findByText('OLD-ORDER')).toBeInTheDocument();
    expect(drawer.getByText('金额需核对')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /复制新建|登记补收|确认提交|审核通过|退回修改/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    expect(screen.getByText(/历史收款仅供查询和打印/)).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => ['POST', 'PATCH'].includes(options?.method))).toBe(false);
    expect(global.fetch.mock.calls.some(([url]) => /receivable-adjustments|receivables\/orders/.test(url))).toBe(false);
});

test('history and printing target the original legacy receipt', async () => {
    render(<LegacyReceiptHistory />); await screen.findByRole('button', { name: receipt.receipt_no });
    fireEvent.click(screen.getByRole('button', { name: /打\s*印/ }));
    expect(printReceipt).toHaveBeenCalledWith(9, expect.any(Object));
    fireEvent.click(screen.getByRole('button', { name: /历\s*史/ }));
    expect(await screen.findByText('旧版记录可能存在缺口')).toBeInTheDocument();
    expect(requests('/api/receipts/9/history')).toHaveLength(1);
    expect(requests('/api/receipts/9/history')[0][1].headers['x-token']).toBeTruthy();
});

test('legacy filters reset pagination without recreating an order collection', async () => {
    render(<LegacyReceiptHistory />); await screen.findByRole('button', { name: receipt.receipt_no });
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => expect(new URL(requests('/api/receipts').slice(-1)[0][0], 'http://localhost').searchParams.get('p')).toBe('2'));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '历史收款状态' }));
    fireEvent.click(await screen.findByText('已驳回', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => {
        const params = new URL(requests('/api/receipts').slice(-1)[0][0], 'http://localhost').searchParams;
        expect(params.get('status')).toBe('rejected');
    });
    expect(new URL(requests('/api/receipts').slice(-1)[0][0], 'http://localhost').searchParams.get('p')).toBe('1');
    expect(screen.queryByRole('button', { name: /复制新建|登记补收/ })).not.toBeInTheDocument();
});

test('closing a pending legacy detail request prevents it reopening after the response arrives', async () => {
    let finishDetail; const original = global.fetch.getMockImplementation();
    global.fetch.mockImplementation(rawUrl => new URL(rawUrl, 'http://localhost').pathname === '/api/receipts/9'
        ? new Promise(resolve => { finishDetail = resolve; }) : original(rawUrl));
    render(<LegacyReceiptHistory />);
    fireEvent.click(await screen.findByRole('button', { name: receipt.receipt_no }));
    await waitFor(() => expect(finishDetail).toBeDefined());
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /close/i }));
    await act(async () => finishDetail(response(receipt)));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByText('OLD-ORDER')).not.toBeInTheDocument();
});
