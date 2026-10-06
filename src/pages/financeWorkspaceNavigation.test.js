import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import FinanceWorkspace from './financeWorkspace';

jest.mock('./financeAccounting', () => ({ initialTab, sectionToken }) => <div>{`会计导航 ${initialTab} ${sectionToken}`}</div>);
jest.mock('../components/FinanceHistoryDrawer', () => () => null);
beforeEach(() => {
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
    global.fetch = jest.fn(url => Promise.resolve({ ok: true, json: async () => ({ code: 200, data: String(url).includes('/dashboard') ? { legacy_reconciliation_required: 4, draft_documents: 0, draft_payments: 0, pending_payments: 3, recent_documents: [] } : { items: [], totals: {} } }) }));
});
afterEach(() => jest.restoreAllMocks());

test('legacy reconciliation tasks navigate directly to accounting migration and can be reopened', async () => {
    render(<FinanceWorkspace />);
    const label = await screen.findByText('旧订单待核对');
    expect(await within(label.closest('.todo')).findByText('4')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '核对差异' }));
    expect(await screen.findByText('会计导航 migration 1')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '会计与月结' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: '总览' }));
    fireEvent.click(screen.getByRole('button', { name: '核对差异' }));
    expect(await screen.findByText('会计导航 migration 2')).toBeInTheDocument();
});


test('pending business payments are visible in home tasks and open the pending filter', async () => {
    render(<FinanceWorkspace />);
    const label = await screen.findByText('待确认收付款');
    const task = label.closest('.todo');
    expect(await within(task).findByText('3')).toBeInTheDocument();
    fireEvent.click(within(task).getByRole('button', { name: '查看' }));
    expect(await screen.findByRole('tab', { name: '收付款' })).toHaveAttribute('aria-selected', 'true');
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/payments?status=pending'))).toBe(true);
});
