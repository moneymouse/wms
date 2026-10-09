import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ReceiptAudit, ReceivableLedger } from './financeReceivables';

jest.mock('../components/FeatureTour', () => function MockFeatureTour({
    autoEnabled,
    forceAutoStart,
    onStepChange,
    onTourEnd,
    steps,
    triggerAriaLabel,
}) {
    return (
        <>
            <button
                aria-label={triggerAriaLabel}
                data-auto-enabled={String(autoEnabled)}
                data-force-auto-start={String(forceAutoStart)}
                onClick={() => onStepChange?.(steps.length - 1)}
            >
                {triggerAriaLabel}
            </button>
            {forceAutoStart && (
                <button
                    aria-label={`完成${triggerAriaLabel}自动流程`}
                    onClick={() => onTourEnd('completed', 'auto')}
                >
                    完成自动流程
                </button>
            )}
        </>
    );
});

const pendingReceipt = {
    id: 21,
    receipt_no: 'RC20260828001',
    customer_name: '测试客户',
    receipt_date: '2026-08-28',
    total_amount: 188,
    creator_name: '业务员A',
    status: 'pending',
    items: [],
};

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 9, roles: ['finance'] }));
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
    global.fetch = jest.fn((url) => {
        let data = [];
        if (url.includes('/receipts?')) data = [pendingReceipt];
        if (url.endsWith('/receipts/21')) data = pendingReceipt;
        if (url.includes('/finance/accounts-receivable')) {
            data = { items: [], totals: {}, total: 0, page: 1, page_size: 20 };
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data }) });
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('the audit tour can open a pending receipt for explanation without reviewing it', async () => {
    render(<ReceiptAudit />);
    await screen.findByText('RC20260828001');

    const trigger = screen.getByRole('button', { name: '打开收款审核操作引导' });
    expect(trigger).toHaveAttribute('data-auto-enabled', 'false');
    fireEvent.click(trigger);

    expect(await screen.findByText('收款审核 - RC20260828001')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/receipts/21'))).toBe(true));
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false);
});

test('receipt audit can search by receipt number', async () => {
    render(<ReceiptAudit />);
    await screen.findByText('RC20260828001');

    fireEvent.change(screen.getByPlaceholderText('收款单号'), {
        target: { value: 'RC20260828001' },
    });
    fireEvent.click(screen.getByRole('button', { name: /搜\s*索/ }));

    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => (
        url.includes('/receipts?') && url.includes('q=RC20260828001')
    ))).toBe(true));
});

test('the receivable ledger exposes stable targets for filters, totals and details', async () => {
    const { container } = render(<ReceivableLedger />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const ledgerRequest = global.fetch.mock.calls.find(([url]) => url.includes('/finance/accounts-receivable'))?.[0];
    const params = new URLSearchParams(ledgerRequest.split('?')[1]);
    // An unrestricted initial range keeps prior-month arrears visible.
    expect(params.has('date_from')).toBe(false);
    expect(params.has('date_to')).toBe(false);
    expect(params.has('as_of')).toBe(false);
    expect(screen.getByPlaceholderText('开始日期')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('结束日期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开应收账款操作引导' }))
        .toHaveAttribute('data-auto-enabled', 'false');
    expect(container.querySelector('[data-tour="receivable-filters"]')).toBeInTheDocument();
    expect(container.querySelector('[data-tour="receivable-totals"]')).toBeInTheDocument();
    expect(container.querySelector('[data-tour="receivable-ledger"]')).toBeInTheDocument();
});

test('finance onboarding advances from receipt audit to receivable ledger', async () => {
    window.sessionStorage.setItem('wms:tour-flow:9', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receipt-audit',
    }));
    render(<ReceiptAudit />);

    fireEvent.click(await screen.findByRole('button', {
        name: '完成打开收款审核操作引导自动流程',
    }));

    expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:9'))).toMatchObject({
        stage: 'receivable-ledger',
    });
});

test('finishing the receivable ledger completes the finance onboarding flow', async () => {
    window.sessionStorage.setItem('wms:tour-flow:9', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receivable-ledger',
    }));
    render(<ReceivableLedger />);

    fireEvent.click(await screen.findByRole('button', {
        name: '完成打开应收账款操作引导自动流程',
    }));

    expect(window.sessionStorage.getItem('wms:tour-flow:9')).toBeNull();
});
