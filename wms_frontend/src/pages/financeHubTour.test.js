import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import FinanceHub from './financeHub';
import { saveFeatureTourFlow } from '../common/featureTourState';

jest.mock('./financeReceivables', () => ({
    ReceiptAudit: () => <div>审核引导内容</div>,
}));
jest.mock('./financeOrderSettlements', () => function MockFinanceOrderSettlements() {
    return <div>台账引导内容</div>;
});
jest.mock('./financeCenter', () => function MockFinanceCenter() {
    return null;
});

test('finance can view third-party reconciliation without an upload action', async () => {
    const originalFetch = global.fetch;
    global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: async () => ({ code: 200, data: { items: [], total: 0 } }) }));
    try {
        render(<MemoryRouter><FinanceHub /></MemoryRouter>);
        fireEvent.click(screen.getByRole('tab', { name: '第三方对账' }));
        expect(await screen.findByRole('region', { name: '第三方对账记录' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /上传并对账/ })).not.toBeInTheDocument();
        await waitFor(() => expect(screen.getByRole('region', { name: '对账历史记录' })).toHaveAttribute('aria-busy', 'false'));
        expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/supplier-reconciliation/batches?'))).toBe(true);
        expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/supplier-reconciliation/vendors'))).toBe(false);
    } finally { global.fetch = originalFetch; }
});

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 10, roles: ['finance'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.sessionStorage.setItem('wms:tour-flow:10', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'receipt-audit',
    }));
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
});

test('finance center follows the active onboarding stage across its tabs', async () => {
    render(<FinanceHub />);

    expect((await screen.findByText('审核引导内容')).closest('.ant-tabs-tabpane'))
        .toHaveClass('ant-tabs-tabpane-active');

    saveFeatureTourFlow({
        userId: '10',
        campaignId: 'cost-quote-receipt',
        stage: 'receivable-ledger',
    });

    await waitFor(() => expect(screen.getByText('台账引导内容').closest('.ant-tabs-tabpane'))
        .toHaveClass('ant-tabs-tabpane-active'));
});
