import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import Receipts from './receipts';

jest.mock('../components/FeatureTour', () => () => null);

jest.setTimeout(15000);

const order = {
    uid: 'order-1', order_id: 'ORDER-1', customer_id: 1, customer_name: '客户A',
    receivable_amount: 100, approved_received: 0, pending_amount: 0, available_amount: 100,
};
const receipt = {
    id: 1, receipt_no: 'RC-1', customer_id: 1, customer_name: '客户A',
    receipt_date: '2026-10-05', total_amount: 100, status: 'pending', settlement_status: 'settled',
};

function response(data, params) {
    return { ok: true, json: async () => ({
        code: 200, data, page: Number(params?.get('p') || 1), page_size: 20, total: 21,
    }) };
}

function mockApi({ owners = [{ id: 7, name: '业务员A' }, { id: 8, name: '业务员B' }], receipts } = {}) {
    global.fetch = jest.fn(async url => {
        const parsed = new URL(url, 'http://localhost');
        if (parsed.pathname.endsWith('/work/workers')) return response(owners);
        if (parsed.pathname.endsWith('/customer_list')) return response([{ id: 1, name: '客户A' }]);
        if (parsed.pathname.endsWith('/receivables/orders')) return response([order], parsed.searchParams);
        if (parsed.pathname.endsWith('/receivable-adjustments')) return response([], parsed.searchParams);
        if (parsed.pathname.endsWith('/receipts')) {
            return receipts ? receipts(parsed.searchParams) : response([receipt], parsed.searchParams);
        }
        throw new Error(`Unexpected request: ${url}`);
    });
}

function renderPage(roles = ['admin']) {
    const payload = window.btoa(JSON.stringify({ user_id: 7, name: 'Admin', roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    return render(<MemoryRouter><Receipts /></MemoryRouter>);
}

function queriesFor(path) {
    return global.fetch.mock.calls
        .map(([url]) => new URL(url, 'http://localhost'))
        .filter(url => url.pathname.endsWith(path))
        .map(url => url.searchParams);
}

function lastQuery(path) {
    const queries = queriesFor(path);
    return queries[queries.length - 1];
}

async function selectOwner(label) {
    fireEvent.mouseDown(screen.getByLabelText('业务员'));
    const option = await screen.findByText(label, { selector: '.ant-select-item-option-content' });
    fireEvent.click(option);
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.matchMedia = jest.fn(query => ({
        matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(),
        addEventListener: jest.fn(), removeEventListener: jest.fn(),
    }));
    mockApi();
});

test('admin first requests and record tab default to the current user without an unfiltered load', async () => {
    renderPage();
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(await screen.findByText('业务员A', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(queriesFor('/receivables/orders')).toHaveLength(1);
    expect(queriesFor('/receivable-adjustments')).toHaveLength(1);
    expect(lastQuery('/receivables/orders').get('owner_id')).toBe('7');
    expect(lastQuery('/receivable-adjustments').get('owner_id')).toBe('7');

    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    await screen.findByText('RC-1');
    expect(screen.getByLabelText('业务员')).toBeVisible();
    expect(queriesFor('/receipts')).toHaveLength(1);
    expect(lastQuery('/receipts').get('owner_id')).toBe('7');
});

test('clearing the owner shows all scopes and choosing another owner resets paginated records', async () => {
    renderPage();
    await screen.findByRole('link', { name: 'ORDER-1' });
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    await screen.findByText('RC-1');
    fireEvent.click(within(screen.getByRole('tabpanel', { name: '收款单记录' })).getByTitle('2'));
    await waitFor(() => expect(lastQuery('/receipts').get('p')).toBe('2'));
    expect(lastQuery('/receipts').get('owner_id')).toBe('7');

    // Ant Design's Select clear icon has no accessible label or control role.
    // eslint-disable-next-line testing-library/no-node-access
    fireEvent.mouseDown(screen.getByLabelText('业务员').closest('.ant-select').querySelector('.ant-select-clear'));
    await waitFor(() => {
        ['/receivables/orders', '/receivable-adjustments', '/receipts'].forEach(path => {
            expect(lastQuery(path).has('owner_id')).toBe(false);
            expect(lastQuery(path).get('p')).toBe('1');
        });
    });

    await selectOwner('业务员B');
    await waitFor(() => {
        ['/receivables/orders', '/receivable-adjustments', '/receipts'].forEach(path => {
            expect(lastQuery(path).get('owner_id')).toBe('8');
            expect(lastQuery(path).get('p')).toBe('1');
        });
    });
    fireEvent.click(screen.getByRole('tab', { name: '收款登记' }));
    expect(screen.getByText('业务员B', { selector: '.ant-select-selection-item' })).toBeVisible();
});

test('admin without the salesperson role still has a selectable self option', async () => {
    mockApi({ owners: [{ id: 8, name: '业务员B' }] });
    renderPage(['admin']);
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(screen.getByText('Admin', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await selectOwner('业务员B');
    expect(lastQuery('/receivables/orders').get('owner_id')).toBe('8');
    await selectOwner('Admin');
    expect(lastQuery('/receivables/orders').get('owner_id')).toBe('7');
});

test('salespeople keep their server-enforced scope without an admin selector or owner query', async () => {
    renderPage(['salesperson']);
    await screen.findByRole('link', { name: 'ORDER-1' });
    expect(screen.queryByLabelText('业务员')).not.toBeInTheDocument();
    expect(queriesFor('/work/workers')).toHaveLength(0);
    expect(lastQuery('/receivables/orders').has('owner_id')).toBe(false);
    expect(lastQuery('/receivable-adjustments').has('owner_id')).toBe(false);
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    await screen.findByText('RC-1');
    expect(lastQuery('/receipts').has('owner_id')).toBe(false);
});

test('an older owner request cannot replace the selected owner record results', async () => {
    let finishPreviousRequest;
    mockApi({ receipts: params => params.get('owner_id') === '7'
        ? new Promise(resolve => { finishPreviousRequest = resolve; })
        : response([{ ...receipt, receipt_no: 'RC-B' }], params) });
    renderPage();
    await screen.findByRole('link', { name: 'ORDER-1' });
    fireEvent.click(screen.getByRole('tab', { name: '收款单记录' }));
    await waitFor(() => expect(finishPreviousRequest).toBeDefined());
    await selectOwner('业务员B');
    await screen.findByText('RC-B');
    await act(async () => finishPreviousRequest(response([receipt])));
    expect(screen.queryByText('RC-1')).not.toBeInTheDocument();
    expect(screen.getByText('RC-B')).toBeInTheDocument();
});
