import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({
    __esModule: true,
    default: jest.requireActual('antd').Input,
}));
jest.mock('../components/ExportButton', () => function MockExportButton() {
    return null;
});
jest.mock('../components/BoxAssignmentModal', () => function MockBoxAssignmentModal() {
    return null;
});
jest.mock('../components/transportation', () => function MockTransportation() {
    return null;
});
jest.mock('../components/FeatureTour', () => function MockFeatureTour() {
    return null;
});

const buildCargo = (overrides = {}) => ({
    uid: 'cargo-uid',
    transfer_id: 'ORIGINAL-001',
    waybill_id: 'WAYBILL-001',
    tag: 'TAG-001',
    count: 1,
    real_en_name: 'SHOES',
    weight: 1.5,
    price: 10,
    status: 0,
    ...overrides,
});

function createFetch(cargo) {
    return jest.fn((rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.includes('/orders/order-uid/cargo?')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, data: [cargo] }),
            });
        }
        if (url.includes('/salesman')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, data: null }),
            });
        }
        if (url.includes('/users/salespersons') || url.includes('/customs-codes')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, data: [] }),
            });
        }
        if (url.endsWith('/orders/order-uid')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    code: 200,
                    data: {
                        uid: 'order-uid',
                        order_id: 'ORDER-001',
                        customer_ids: null,
                        financial_lock: { active: false, has_history: false },
                    },
                }),
            });
        }
        if (url.endsWith(`/cargo/${cargo.uid}`) && options.method === 'PUT') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, msg: 'success' }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ code: 200, data: [] }),
        });
    });
}

function renderOrderDetail() {
    return render(
        <MemoryRouter initialEntries={['/orders/order-uid']}>
            <Routes>
                <Route path="/orders/:order_id" element={<OrderDetail />} />
            </Routes>
        </MemoryRouter>
    );
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['admin'] }));
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
});

afterEach(() => {
    jest.restoreAllMocks();
});

test.each([
    ['手动创建包裹', buildCargo({ status: 1, waybill_id: '' })],
    ['装箱单分配包裹', buildCargo({ status: 1, packing_list_uid: 'packing-list-001' })],
    ['进入后续物流状态的包裹', buildCargo({ status: 'InTransit_Other' })],
    ['出现未来未知物流状态的包裹', buildCargo({ status: 'FutureCarrierState' })],
])('%s处于出库或后续状态时重量保持只读，保存其他字段也不会提交重量', async (_, cargo) => {
    global.fetch = createFetch(cargo);
    renderOrderDetail();

    const weightText = await screen.findByText('1.5KG');
    const editButton = within(weightText.closest('tr')).getByRole('button', { name: /编\s*辑/ });
    fireEvent.click(editButton);

    const waybillInput = cargo.waybill_id
        ? await screen.findByDisplayValue(cargo.waybill_id)
        : within(weightText.closest('tr')).getAllByRole('textbox')[1];
    expect(screen.queryByDisplayValue('1.5')).not.toBeInTheDocument();
    expect(weightText).toBeInTheDocument();
    expect(weightText).toHaveAttribute('title', '货物已出库，重量不可修改');

    fireEvent.change(waybillInput, { target: { value: 'WAYBILL-NEW' } });
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => (
            String(url).endsWith(`/cargo/${cargo.uid}`) && options?.method === 'PUT'
        ));
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ waybill_id: 'WAYBILL-NEW' });
    });
});

test.each([
    ['手动创建包裹', buildCargo({ status: 0, waybill_id: 'LEGACY-WAYBILL', weight: 3.5 })],
    ['装箱单分配包裹', buildCargo({
        packing_list_uid: 'packing-list-001',
        status: 0,
        track_status: 'Delivered_Other',
        waybill_id: '   ',
        weight: 4.5,
    })],
    ['待分配包裹', buildCargo({ status: 'pending_assign', waybill_id: '', weight: 5.5 })],
])('%s仍处于待出库状态时可编辑重量', async (_, cargo) => {
    global.fetch = createFetch(cargo);
    renderOrderDetail();

    fireEvent.click(await screen.findByText(`${cargo.weight}KG`));

    expect(await screen.findByDisplayValue(String(cargo.weight))).toBeInTheDocument();
});

test('首次登记转单号可同时保存最终重量，随后立即进入只读状态', async () => {
    const cargo = buildCargo({ status: 0, waybill_id: '', weight: 6.5 });
    global.fetch = createFetch(cargo);
    renderOrderDetail();

    const weightText = await screen.findByText('6.5KG');
    const row = weightText.closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));

    const textInputs = within(row).getAllByRole('textbox');
    const waybillInput = textInputs[1];
    const weightInput = within(row).getByDisplayValue('6.5');
    fireEvent.change(waybillInput, { target: { value: 'WAYBILL-NEW' } });
    fireEvent.change(weightInput, { target: { value: '7.5' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => (
            String(url).endsWith(`/cargo/${cargo.uid}`) && options?.method === 'PUT'
        ));
        expect(JSON.parse(updateCall[1].body)).toMatchObject({
            waybill_id: 'WAYBILL-NEW',
            weight: '7.5',
        });
    });

    const lockedWeight = await screen.findByText('7.5KG');
    expect(lockedWeight).toHaveAttribute('title', '货物已出库，重量不可修改');
    fireEvent.click(lockedWeight);
    expect(screen.queryByDisplayValue('7.5')).not.toBeInTheDocument();
});
