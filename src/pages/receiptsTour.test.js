import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import Receipts from './receipts';

jest.mock('../components/FeatureTour', () => function MockFeatureTour({
    autoEnabled,
    forceAutoStart,
    onStepChange,
    onTourEnd,
    steps,
}) {
    return (
        <>
            <button
                aria-label="测试收款引导"
                data-auto-enabled={String(autoEnabled)}
                data-force-auto-start={String(forceAutoStart)}
                onClick={() => onStepChange(steps.length - 1)}
            >
                测试收款引导
            </button>
            {forceAutoStart && (
                <button aria-label="完成自动收款引导" onClick={() => onTourEnd('completed', 'auto')}>
                    完成自动收款引导
                </button>
            )}
        </>
    );
});

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
        }),
    });
    global.fetch = jest.fn((url) => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(url.includes('/receipts?')
            ? { code: 200, data: [], page: 1, page_size: 20, total: 0 }
            : { code: 200, data: [] }),
    }));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('the receipt page loads all salesperson receivables without a customer filter', async () => {
    render(<MemoryRouter><Receipts /></MemoryRouter>);

    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => (
        url.includes('/receivables/orders')
        && url.includes('p=1')
        && url.includes('s=20')
        && !url.includes('customer_id=')
    ))).toBe(true));
});

test('an unsettled order number links to its order detail page', async () => {
    global.fetch = jest.fn(url => Promise.resolve({
        ok: true,
        json: () => Promise.resolve(url.includes('/receivables/orders')
            ? {
                code: 200,
                data: [{
                    uid: 'order-uid-1',
                    order_id: 'ORDER-1',
                    customer_id: 1,
                    customer_name: '客户A',
                    billing_weight: 1,
                    receivable_amount: 100,
                    approved_received: 0,
                    pending_amount: 0,
                    available_amount: 100,
                }],
                page: 1,
                page_size: 20,
                total: 1,
            }
            : { code: 200, data: [] }),
    }));

    render(<MemoryRouter><Receipts /></MemoryRouter>);

    expect(await screen.findByRole('link', { name: 'ORDER-1' }))
        .toHaveAttribute('href', '/orders/order-uid-1');
});

test('the receipt tour changes to the records tab without submitting data', async () => {
    const { container } = render(<MemoryRouter><Receipts /></MemoryRouter>);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const trigger = screen.getByRole('button', { name: '测试收款引导' });
    expect(trigger).toHaveAttribute('data-auto-enabled', 'false');
    fireEvent.click(trigger);

    await waitFor(() => {
        const records = container.querySelector('[data-tour="receipt-records"]');
        expect(records).toBeInTheDocument();
        expect(records.closest('.ant-tabs-tabpane')).toHaveClass('ant-tabs-tabpane-active');
    });
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test('the receipt page does not start the full onboarding workflow by itself', async () => {
    render(<MemoryRouter><Receipts /></MemoryRouter>);

    expect(await screen.findByRole('button', { name: '测试收款引导' }))
        .toHaveAttribute('data-auto-enabled', 'false');
    expect(window.sessionStorage.getItem('wms:tour-flow:7')).toBeNull();
});

test('admin business onboarding ends after receipt entry instead of continuing to finance', async () => {
    const payload = window.btoa(JSON.stringify({ user_id: 8, roles: ['admin'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.sessionStorage.setItem('wms:tour-flow:8', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receipt-entry',
    }));

    render(<MemoryRouter><Receipts /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '完成自动收款引导' }));

    expect(window.sessionStorage.getItem('wms:tour-flow:8')).toBeNull();
});
