import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FinanceRevenue from './financeRevenue';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../common/safeHeader', () => () => ({ 'x-token': 'test' }));
jest.mock('../components/FinanceHistoryDrawer', () => () => null);
const invoice = { id: 7, number: 'INV-TEST-007', partner_name: '测试客户', document_date: '2026-01-05', subtotal: '100.00', deferred_amount: '60.00', recognized_amount: '40.00', version: 3, entries: [] };
const ok = data => ({ ok: true, json: async () => ({ code: 200, data }) });
beforeEach(() => {
    window.matchMedia = jest.fn().mockImplementation(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn() }));
    global.fetch = jest.fn().mockImplementation(async (url, options) => options?.method === 'POST'
        ? ok({ invoice: { ...invoice, deferred_amount: '40.00', recognized_amount: '60.00' }, entry: { id: 9 } })
        : ok(url.includes('?') ? { items: [invoice], total: 1, revenue_policy: 'deferred' } : invoice));
});
afterEach(() => jest.restoreAllMocks());

test('lists remaining performance obligation and submits a partial recognition with version and idempotency', async () => {
    render(<FinanceRevenue />);
    expect(await screen.findByText('INV-TEST-007')).toBeInTheDocument();
    expect(screen.getByText('60.00')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认收入' }));
    fireEvent.change(screen.getByLabelText('本次确认金额（CNY，未税）'), { target: { value: '20.00' } });
    fireEvent.change(screen.getByLabelText('履约依据'), { target: { value: '客户回执 R-001' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并生成凭证' }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true));
    const [url, options] = global.fetch.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(url).toBe('/api/finance/v2/revenue/7/recognize');
    expect(JSON.parse(options.body)).toMatchObject({ amount: '20', version: 3, reason: '客户回执 R-001', idempotency_key: expect.any(String), recognition_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) });
});

test('invoice policy explains why a second revenue recognition is disabled', async () => {
    global.fetch.mockResolvedValue(ok({ items: [{ ...invoice, deferred_amount: '0.00', recognized_amount: '100.00' }], total: 1, revenue_policy: 'invoice' }));
    render(<FinanceRevenue />);
    expect(await screen.findByText('当前账簿按账单确认收入')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认收入' })).toBeDisabled();
});

test('network retry preserves the idempotency key', async () => {
    let attempts = 0;
    global.fetch.mockImplementation(async (url, options) => {
        if (options?.method === 'POST') {
            attempts += 1;
            if (attempts === 1) throw new Error('网络中断');
            return ok({ invoice, entry: { id: 9 } });
        }
        return ok({ items: [invoice], total: 1, revenue_policy: 'deferred' });
    });
    render(<FinanceRevenue />);
    await screen.findByText('INV-TEST-007');
    fireEvent.click(screen.getByRole('button', { name: '确认收入' }));
    fireEvent.change(screen.getByLabelText('履约依据'), { target: { value: '回执完成' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并生成凭证' }));
    expect(await screen.findByText('网络中断')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认并生成凭证' }));
    await waitFor(() => expect(attempts).toBe(2));
    const bodies = global.fetch.mock.calls.filter(([, options]) => options?.method === 'POST').map(([, options]) => JSON.parse(options.body));
    expect(bodies[0].idempotency_key).toBe(bodies[1].idempotency_key);
});

function RevenueNavigation() {
    const location = useLocation();
    const navigate = useNavigate();
    return <><output data-testid="revenue-url">{location.search}{location.hash}</output><button onClick={() => navigate(-1)}>返回旧筛选</button></>;
}

test('revenue restores filters and pagination from URLs and follows browser back navigation', async () => {
    const previous = new URLSearchParams({ revenueFilters: JSON.stringify({ p: 2, s: 15, open_only: 'false', q: '旧客户' }), keep: 'yes' });
    const current = new URLSearchParams({ revenueFilters: JSON.stringify({ p: 4, s: 15, open_only: 'true', q: '新客户' }), keep: 'yes' });
    render(<MemoryRouter initialEntries={[`/finance?${previous}#ledger`, `/finance?${current}#ledger`]} initialIndex={1}><FinanceRevenue /><RevenueNavigation /></MemoryRouter>);
    expect(screen.getByLabelText('搜索待履约账单')).toHaveValue('新客户');
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const params = new URL(url, 'http://localhost').searchParams;
        return params.get('p') === '4' && params.get('q') === '新客户' && params.get('open_only') === 'true';
    })).toBe(true));
    fireEvent.change(screen.getByLabelText('搜索待履约账单'), { target: { value: '更新客户' } });
    await waitFor(() => {
        const url = new URL(`http://localhost/${screen.getByTestId('revenue-url').textContent}`);
        expect(JSON.parse(url.searchParams.get('revenueFilters'))).toMatchObject({ q: '更新客户', p: 1 });
        expect(url.searchParams.get('keep')).toBe('yes');
        expect(url.hash).toBe('#ledger');
    });
    fireEvent.click(screen.getByText('返回旧筛选'));
    await waitFor(() => expect(screen.getByLabelText('搜索待履约账单')).toHaveValue('旧客户'));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => {
        const params = new URL(url, 'http://localhost').searchParams;
        return params.get('p') === '2' && params.get('q') === '旧客户' && params.get('open_only') === 'false';
    })).toBe(true));
});
