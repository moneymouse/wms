import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Receipts from './receipts';
import FeatureTour from '../components/FeatureTour';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../components/FeatureTour', () => jest.fn(() => null));
function renderPage() { return render(<MemoryRouter><Receipts /></MemoryRouter>); }
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear();
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }))}.s`);
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ code: 200, data: { items: [], total: 0, page: 1, page_size: 20 } }) }));
    FeatureTour.mockClear();
});
afterEach(() => jest.restoreAllMocks());

test('the payment entry opens without the old order-picking or quote-adjustment workflow', async () => {
    renderPage(); await screen.findByText('暂无收付款记录');
    expect(screen.getByRole('button', { name: /登记收款/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /登记付款/ })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '生成并提交收款单' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.every(([url]) => String(url).startsWith('/api/finance/v2/payments?'))).toBe(true);
    expect(FeatureTour).not.toHaveBeenCalled();
});

test.each(['receipt-navigation', 'receipt-entry', 'receipt-audit'])('legacy %s continuation is cleared without submitting or selecting orders', async stage => {
    window.sessionStorage.setItem('wms:tour-flow:7', JSON.stringify({ campaignId: 'cost-quote-receipt', stage }));
    renderPage(); await screen.findByText('暂无收付款记录');
    await waitFor(() => expect(window.sessionStorage.getItem('wms:tour-flow:7')).toBeNull());
    expect(FeatureTour).not.toHaveBeenCalled(); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => ['POST', 'PATCH'].includes(options?.method))).toBe(false);
    expect(global.fetch.mock.calls.some(([url]) => /receivables|receivable-adjustments|order-allocations/.test(url))).toBe(false);
});

test('opening the page does not create a new tour flow', async () => {
    renderPage(); await screen.findByText('暂无收付款记录');
    expect(window.sessionStorage.getItem('wms:tour-flow:7')).toBeNull();
    expect(screen.getByRole('tab', { name: '收付款记录' })).toHaveAttribute('aria-selected', 'true');
    expect(FeatureTour).not.toHaveBeenCalled();
});

test('opening payments preserves another campaign continuation', async () => {
    const flow = JSON.stringify({ campaignId: 'another-workflow', stage: 'receipt-entry' });
    window.sessionStorage.setItem('wms:tour-flow:7', flow);
    renderPage(); await screen.findByText('暂无收付款记录');
    expect(window.sessionStorage.getItem('wms:tour-flow:7')).toBe(flow);
    expect(FeatureTour).not.toHaveBeenCalled();
});
