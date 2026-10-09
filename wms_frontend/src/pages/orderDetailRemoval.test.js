import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/transportation', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);

function setup(cargos, role = 'admin') {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: [role] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    let current = cargos;
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const url = String(rawUrl);
        let data = [];
        if (url.includes('/orders/order-uid/cargo?')) data = current;
        else if (url.endsWith('/orders/order-uid')) data = {
            uid: 'order-uid', order_id: 'ORDER-001', customer_ids: null,
            financial_lock: { active: false, has_history: false },
        };
        else if (url.includes('/salesman')) data = null;
        else if (url.endsWith('/undo-outbound') && options.method === 'POST') {
            current = current.map(row => ({ ...row, status: 0, date: null, waybill_id: '', removal_allowed: true }));
        } else if (url.endsWith('/cargo/unbind')) {
            const ids = JSON.parse(options.body).cargo_id_list;
            current = current.filter(row => !ids.includes(row.uid));
            data = { success: ids, failed: [] };
        }
        return { ok: true, json: async () => ({ code: 200, data }) };
    });
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}><Routes>
        <Route path="/orders/:order_id" element={<OrderDetail />} />
    </Routes></MemoryRouter>);
}

const cargo = (overrides = {}) => ({
    uid: 'cargo-uid', transfer_id: 'PACKAGE-001', waybill_id: 'WB-001',
    count: 1, weight: 1.5, price: 10, status: 1, removal_allowed: false,
    ...overrides,
});

async function findCargoRow() {
    await screen.findByText('PACKAGE-001');
    return screen.getAllByRole('row').find(row => within(row).queryByText('PACKAGE-001'));
}

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({ matches: false, media: query, onchange: null,
            addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() {} }),
    });
});
afterEach(() => jest.restoreAllMocks());

test('已出库包裹禁止单行与混合批量移除，管理员先撤销后可以移除', async () => {
    setup([cargo(), cargo({ uid: 'pending', transfer_id: 'PACKAGE-002', status: 0, removal_allowed: true })]);
    const row = await findCargoRow();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeDisabled();
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(await screen.findByRole('button', { name: /批量移除/ })).toBeDisabled();
    fireEvent.click(within(row).getByRole('button', { name: '撤销出库' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认撤销' }));
    await waitFor(() => expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeEnabled());
    expect(global.fetch.mock.calls.filter(([url]) => String(url).endsWith('/undo-outbound'))).toHaveLength(1);
    fireEvent.click(within(row).getByRole('button', { name: /移\s*除/ }));
    fireEvent.click(await screen.findByRole('button', { name: '确认移除' }));
    await waitFor(() => expect(screen.queryByText('PACKAGE-001')).not.toBeInTheDocument());
    expect(global.fetch.mock.calls.find(([url]) => String(url).endsWith('/cargo/unbind'))).toBeDefined();
});

test('业务员看不到撤销出库入口且仍不能移除已出库包裹', async () => {
    setup([cargo()], 'salesperson');
    const row = await findCargoRow();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeDisabled();
    expect(within(row).queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
});

test('撤销后的当前状态优先于物流平台仍返回的旧状态', async () => {
    setup([cargo({ status: 'Delivered', removal_allowed: true, waybill_id: '', date: null })]);
    const row = await findCargoRow();
    expect(within(row).getByRole('button', { name: /移\s*除/ })).toBeEnabled();
    expect(within(row).queryByRole('button', { name: '撤销出库' })).not.toBeInTheDocument();
});
