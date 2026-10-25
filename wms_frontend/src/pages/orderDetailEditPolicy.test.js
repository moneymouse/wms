import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ORDER_EDIT_POLICY_KEYS } from '../common/orderEditPolicy';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({
    __esModule: true,
    default: jest.requireActual('antd').Input,
}));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => function MockTransportation({ defaultValue, onChange, onBlur }) {
    return <input aria-label="运输方式" defaultValue={defaultValue} onChange={event => onChange(event.target.value)} onBlur={onBlur} />;
});

const editablePolicy = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));
const cargo = {
    uid: 'cargo-1', transfer_id: 'OLD-1', waybill_id: 'WB-1', tag: 'TAG-1',
    weight: 10.5, count: 1, real_en_name: 'SHOES', status: 1,
};

const buildOrder = (overrides = {}) => ({
    uid: 'order-uid', order_id: 'ORDER-1', transportation: 'DHL', total_weight: 10.5,
    salesman: { id: 7, name: '业务员甲' }, customer_ids: null,
    edit_policy: { ...editablePolicy, fully_outbound: true },
    ...overrides,
});

function setJwt(roles = ['admin', 'salesperson'], userId = 7) {
    const payload = window.btoa(JSON.stringify({ user_id: userId, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}

function mockFetch(order = buildOrder(), currentCargo = cargo) {
    global.fetch = jest.fn(rawUrl => {
        const url = String(rawUrl);
        let data = [];
        if (url.includes('/salesman')) data = order.salesman;
        else if (url.includes('/cargo?')) data = [currentCargo];
        else if (url.endsWith('/orders/order-uid')) data = order;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data }) });
    });
}

function renderOrder() {
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}>
        <Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes>
    </MemoryRouter>);
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    setJwt();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});

afterEach(() => jest.restoreAllMocks());

test('fully outbound orders allow transportation and tracking edits without lock actions', async () => {
    mockFetch();
    renderOrder();
    const transportation = await screen.findByText('DHL');
    fireEvent.click(transportation.parentElement.querySelector('.ant-typography-edit'));
    expect(await screen.findByRole('textbox', { name: '运输方式' })).toHaveValue('DHL');

    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    expect(await within(row).findByDisplayValue('OLD-1')).not.toBeDisabled();
    expect(within(row).getByDisplayValue('WB-1')).not.toBeDisabled();
    expect(within(row).queryByDisplayValue('10.5')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /锁定|解锁/ })).not.toBeInTheDocument();
    expect(screen.queryByText('订单修订中')).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => /receipt-unlock|receipt-relock/.test(String(url)))).toBe(false);
});

test.each(['locked', 'revision_open'])('obsolete %s metadata does not restrict editing or expose revision controls', async status => {
    mockFetch(buildOrder({
        edit_policy: undefined,
        receipt_locked: true,
        receipt_lock: { status, has_history: true, revision: { reason: '历史原因' } },
        financial_lock: { active: true, has_history: true },
    }), { ...cargo, status: 0 });
    renderOrder();
    await waitFor(() => expect(screen.getByRole('button', { name: /添\s*加/ })).not.toBeDisabled());
    expect(screen.getByRole('button', { name: /从装箱单分配/ })).not.toBeDisabled();
    expect(screen.queryByRole('button', { name: /锁定|解锁/ })).not.toBeInTheDocument();
    expect(screen.queryByText('订单修订中')).not.toBeInTheDocument();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    expect(await within(row).findByDisplayValue('OLD-1')).not.toBeDisabled();
    expect(within(row).getByDisplayValue('10.5')).not.toBeDisabled();
});

test('ordinary salesperson permissions still protect another salespersons transportation', async () => {
    setJwt(['salesperson'], 99);
    mockFetch(buildOrder({ edit_policy: undefined }));
    renderOrder();
    const transportation = await screen.findByText('DHL');
    expect(transportation.parentElement.querySelector('.ant-typography-edit')).toBeNull();
    expect(screen.queryByRole('button', { name: /dollar\s*报价$/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /报价版本/ })).toBeInTheDocument();
});

test.each([
    ['outbound box', { status: 1, identity_editable: false }],
    ['pending box explicitly denied original number edits', { status: 0, identity_editable: true, original_number_editable: false, waybill_id: '' }],
    ['numeric logistics state without identity metadata', { status: 2 }],
    ['string logistics state with permissive identity metadata', { status: '3', identity_editable: true }],
    ['outbound box without waybill', { status: 1, waybill_id: '', identity_editable: true, original_number_editable: true }],
    ['later tracking state', { status: 'InTransit_Other', identity_editable: true }],
    ['pending status with current shipment date', { status: 0, date: '2026-10-06', original_number_editable: true }],
])('%s keeps the original number read only while allowing waybill changes', async (_, overrides) => {
    const box = { ...cargo, packing_list_uid: 'packing-list-1', ...overrides };
    mockFetch(buildOrder(), box);
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    expect(within(row).queryByDisplayValue('OLD-1')).not.toBeInTheDocument();
    expect(within(row).getByText('OLD-1')).toBeInTheDocument();
    const waybillInput = box.waybill_id
        ? await within(row).findByDisplayValue(box.waybill_id)
        : within(row).getAllByRole('textbox')[0];
    expect(waybillInput).not.toBeDisabled();
    fireEvent.change(waybillInput, { target: { value: 'WB-NEW' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ waybill_id: 'WB-NEW' });
    });
});

test('a box that has never shipped can edit its original number', async () => {
    mockFetch(buildOrder(), { ...cargo, status: 0, packing_list_uid: 'packing-list-1', identity_editable: true });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    expect(await within(row).findByDisplayValue('OLD-1')).not.toBeDisabled();
});

test.each([0, 'pending_outbound'])('a returned box in %s status can save a changed original number while its box identity remains locked', async status => {
    mockFetch(buildOrder(), {
        ...cargo, status, date: null, waybill_id: '', packing_list_uid: 'packing-list-1',
        identity_editable: false, original_number_editable: true,
    });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    const originalInput = await within(row).findByDisplayValue('OLD-1');
    expect(originalInput).not.toBeDisabled();
    fireEvent.change(originalInput, { target: { value: 'RETURNED-NEW' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ transfer_id: 'RETURNED-NEW' });
    });
});

test('ordinary outbound cargo can still change its original number despite identity metadata', async () => {
    mockFetch(buildOrder(), { ...cargo, identity_editable: false });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    const originalInput = await within(row).findByDisplayValue('OLD-1');
    expect(originalInput).not.toBeDisabled();
    fireEvent.change(originalInput, { target: { value: 'ORIGINAL-NEW' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ transfer_id: 'ORIGINAL-NEW' });
    });
});

test.each([0, '0', '0.00'])('zero declared value %s starts blank and remains unchanged when saved without input', async price => {
    mockFetch(buildOrder(), { ...cargo, price });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));

    const priceInput = within(row).getAllByRole('cell')[7].querySelector('input');
    expect(priceInput).toHaveValue('');
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => expect(within(row).getByRole('button', { name: /编\s*辑/ })).toBeEnabled());
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false);
    expect(within(row).getAllByRole('cell')[7]).toHaveTextContent(String(price));
});

test('editing another cargo field leaves the blank zero declared value out of the update', async () => {
    mockFetch(buildOrder(), { ...cargo, price: 0 });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue('WB-1'), { target: { value: 'WB-NEW' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ waybill_id: 'WB-NEW' });
    });
});

test.each([0, '25.50'])('declared value %s can be edited and saves the entered decimal amount', async price => {
    mockFetch(buildOrder(), { ...cargo, price });
    renderOrder();
    const row = (await screen.findByText('OLD-1')).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));

    const priceInput = within(row).getAllByRole('cell')[7].querySelector('input');
    expect(priceInput).toHaveValue(price === 0 ? '' : price);
    fireEvent.change(priceInput, { target: { value: '0.5' } });
    fireEvent.keyDown(priceInput, { key: 'Enter', code: 'Enter', keyCode: 13 });

    await waitFor(() => {
        const updateCall = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(updateCall).toBeDefined();
        expect(JSON.parse(updateCall[1].body)).toEqual({ price: '0.5' });
    });
    expect(await within(row).findByText('0.5')).toBeInTheDocument();
});
