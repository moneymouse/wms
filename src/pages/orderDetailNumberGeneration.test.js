import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { ORDER_EDIT_POLICY_KEYS } from '../common/orderEditPolicy';
import OrderDetail from './orderDetail';

jest.setTimeout(15000);

jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);

const policy = Object.fromEntries(ORDER_EDIT_POLICY_KEYS.map(key => [key, true]));
const order = {
    uid: 'order-uid', order_id: '8888888888', transportation: 'DHL', customer_ids: null,
    salesman: { id: 7, name: '业务员甲' }, edit_policy: policy,
};
const cargo = {
    uid: 'cargo-1', transfer_id: '8777777777', waybill_id: '', tag: 'TAG-1',
    count: 1, real_en_name: 'SHOES', weight: 2, price: 10, status: 0,
};
const box = {
    ...cargo, uid: 'box-1', transfer_id: '8666666666', tag: 'BOX-1',
    packing_list_uid: 'packing-list-1', identity_editable: true,
};
const response = (data, code = 200, msg = '') => Promise.resolve({
    ok: code === 200, status: code, json: () => Promise.resolve({ code, data, msg }),
});
const generationCalls = () => global.fetch.mock.calls.filter(([url]) => String(url).includes('/generate-'));

function setup({ roles = ['salesperson'], orderOverrides = {}, cargos = [cargo, box], onGenerate, onPut } = {}) {
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    let currentOrder = { ...order, ...orderOverrides };
    let currentCargo = cargos.map(item => ({ ...item }));
    global.fetch = jest.fn((rawUrl, options = {}) => {
        const url = String(rawUrl);
        if (url.includes('/generate-')) {
            if (onGenerate) return onGenerate(url, options);
            if (url.endsWith('/generate-order-number')) {
                currentOrder = { ...currentOrder, order_id: '812345678' };
                return response({ order_id: currentOrder.order_id });
            }
            return response({ transfer_id: '823456789' });
        }
        if (options.method === 'PUT') {
            const data = JSON.parse(options.body);
            if (url.endsWith('/orders/order-uid')) currentOrder = { ...currentOrder, ...data };
            else currentCargo = currentCargo.map(item => url.endsWith(`/cargo/${item.uid}`) ? { ...item, ...data } : item);
            if (onPut) return onPut(url, options);
            return response({});
        }
        if (url.includes('/cargo?')) return response(currentCargo);
        if (url.endsWith('/orders/order-uid')) return response(currentOrder);
        if (url.endsWith('/orders/next-order')) return response({ ...order, uid: 'next-order', order_id: 'NEXT-ORDER' });
        if (url.endsWith('/salesman')) return response(currentOrder.salesman);
        return response([]);
    });
}

function Navigation() {
    const navigate = useNavigate();
    return <button onClick={() => navigate('/orders/next-order')}>切换订单</button>;
}
function renderOrder() {
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}>
        <Navigation />
        <Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes>
    </MemoryRouter>);
}

function editOrderNumber() {
    const orderNumber = screen.getByText(order.order_id);
    fireEvent.click(orderNumber.querySelector('.ant-typography-edit'));
    return screen.getByRole('textbox', { name: '订单号' });
}

function finishOrderNumberEdit() {
    fireEvent.keyDown(screen.getByRole('textbox', { name: '订单号' }), { key: 'Escape' });
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});
afterEach(() => jest.restoreAllMocks());

test('opening and editing never generate numbers; each click saves only the selected target', async () => {
    setup();
    renderOrder();
    await screen.findByText(order.order_id);
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    expect(generationCalls()).toHaveLength(0);
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    expect(generationCalls()).toHaveLength(0);
    expect(within(row).getByRole('button', { name: '生成原单号' })).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: /取\s*消/ }));
    expect(screen.queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
    editOrderNumber();
    expect(generationCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: '生成订单号' }));
    expect(await screen.findByDisplayValue('812345678')).toBeInTheDocument();
    finishOrderNumberEdit();
    expect(screen.getByText('812345678')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    expect(generationCalls()).toHaveLength(1);
    expect(generationCalls()[0][0]).toMatch(/\/orders\/order-uid\/generate-order-number$/);
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({ expected_value: order.order_id });
    const boxRow = screen.getByText(box.transfer_id).closest('tr');
    fireEvent.click(within(boxRow).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.click(within(boxRow).getByRole('button', { name: '生成原单号' }));
    expect(await within(boxRow).findByDisplayValue('823456789')).toBeInTheDocument();
    fireEvent.click(within(boxRow).getByRole('button', { name: /取\s*消/ }));
    expect(generationCalls()).toHaveLength(2);
    expect(generationCalls()[1][0]).toMatch(/\/orders\/order-uid\/cargo\/box-1\/generate-original-number$/);
    expect(JSON.parse(generationCalls()[1][1].body)).toEqual({ expected_value: box.transfer_id });
    expect(screen.getByText(cargo.transfer_id)).toBeInTheDocument();
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
});

test('generation uses the saved original number and preserves other unsaved row fields', async () => {
    setup();
    renderOrder();
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue(cargo.transfer_id), { target: { value: 'MANUAL-DRAFT' } });
    fireEvent.change(within(row).getByDisplayValue(cargo.tag), { target: { value: 'UNSAVED-TAG' } });
    const button = within(row).getByRole('button', { name: '生成原单号' });
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    expect(await within(row).findByDisplayValue('823456789')).toBeInTheDocument();
    expect(within(row).getByDisplayValue('UNSAVED-TAG')).toBeInTheDocument();
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({ expected_value: cargo.transfer_id });
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const put = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(JSON.parse(put[1].body)).toEqual({ tag: 'UNSAVED-TAG' });
    });
    expect(within(row).getByText('823456789')).toBeInTheDocument();
});

test('generation icons explain that they randomly generate and save the number', async () => {
    setup();
    renderOrder();
    await screen.findByText(order.order_id);
    editOrderNumber();
    const orderButton = screen.getByRole('button', { name: '生成订单号' });
    expect(orderButton.querySelector('[aria-label="reload"]')).toBeInTheDocument();
    fireEvent.mouseOver(orderButton);
    expect(await screen.findByRole('tooltip', { name: '随机生成并保存订单号' })).toBeInTheDocument();
    finishOrderNumberEdit();
    const row = screen.getByText(cargo.transfer_id).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    const originalButton = within(row).getByRole('button', { name: '生成原单号' });
    expect(originalButton.querySelector('[aria-label="reload"]')).toBeInTheDocument();
    fireEvent.mouseOver(originalButton);
    expect(await screen.findByRole('tooltip', { name: '随机生成并保存原单号' })).toBeInTheDocument();
    expect(generationCalls()).toHaveLength(0);
});

test('order generation replaces the draft and blocks repeated clicks and stale manual saves', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderOrder();
    await screen.findByText(order.order_id);
    const input = editOrderNumber();
    fireEvent.change(input, { target: { value: 'MANUAL-DRAFT' } });
    const button = screen.getByRole('button', { name: '生成订单号' });
    fireEvent.mouseDown(button);
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(input).toHaveAttribute('readonly');
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 13, code: 'Enter' });
    fireEvent.blur(input);
    expect(generationCalls()).toHaveLength(1);
    expect(JSON.parse(generationCalls()[0][1].body)).toEqual({ expected_value: order.order_id });
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
    await act(async () => { resolve(await response({ order_id: '812345678' })); });
    expect(await screen.findByDisplayValue('812345678')).not.toHaveAttribute('readonly');
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 13, code: 'Enter' });
    expect(await screen.findByText('812345678')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
});

test('canceling order editing during generation keeps the completed number saved and the editor closed', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderOrder();
    await screen.findByText(order.order_id);
    editOrderNumber();
    fireEvent.click(screen.getByRole('button', { name: '生成订单号' }));
    finishOrderNumberEdit();
    expect(screen.queryByRole('textbox', { name: '订单号' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    await act(async () => { resolve(await response({ order_id: '812345678' })); });
    expect(await screen.findByText('812345678')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: '订单号' })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(0);
});

test('a pending request prevents repeated generation and stale manual saves for that cargo', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderOrder();
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    const button = within(row).getByRole('button', { name: '生成原单号' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(within(row).getByDisplayValue(cargo.transfer_id)).toBeDisabled();
    expect(within(row).getByRole('button', { name: /保\s*存/ })).toBeDisabled();
    expect(generationCalls()).toHaveLength(1);
    fireEvent.change(within(row).getByDisplayValue(cargo.tag), { target: { value: 'UNSAVED-TAG' } });
    fireEvent.keyDown(within(row).getByDisplayValue('UNSAVED-TAG'), { key: 'Enter', keyCode: 13, code: 'Enter' });
    expect(within(row).getByDisplayValue('UNSAVED-TAG')).toBeInTheDocument();
    expect(screen.getByText(box.transfer_id)).toBeInTheDocument();
    await act(async () => { resolve(await response({ transfer_id: '823456789' })); });
    expect(await within(row).findByDisplayValue('823456789')).not.toBeDisabled();
    expect(within(row).getByDisplayValue('UNSAVED-TAG')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: /保\s*存/ })).not.toBeDisabled();
});

test('saving another row cannot replace a generated number with an old row snapshot', async () => {
    let resolveSave;
    setup({ onPut: () => new Promise(resolve => { resolveSave = resolve; }) });
    renderOrder();
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue(cargo.tag), { target: { value: 'SAVED-TAG' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => expect(resolveSave).toBeDefined());
    fireEvent.click(within(row).getByRole('button', { name: /取\s*消/ }));
    const boxRow = screen.getByText(box.transfer_id).closest('tr');
    fireEvent.click(within(boxRow).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.click(within(boxRow).getByRole('button', { name: '生成原单号' }));
    await within(boxRow).findByDisplayValue('823456789');
    await act(async () => { resolveSave(await response({})); });
    expect(within(boxRow).getByText('823456789')).toBeInTheDocument();
    expect(within(row).getByText('SAVED-TAG')).toBeInTheDocument();
});

test('a late order refresh cannot restore the old order number after generation succeeds', async () => {
    setup();
    const fetchNormally = global.fetch;
    let reads = 0;
    let resolveRead;
    global.fetch = jest.fn((url, options = {}) => {
        if (String(url).endsWith('/orders/order-uid') && !options.method && ++reads > 1) {
            return new Promise(resolve => { resolveRead = resolve; });
        }
        return fetchNormally(url, options);
    });
    renderOrder();
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue(cargo.tag), { target: { value: 'SAVED-TAG' } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => expect(resolveRead).toBeDefined());
    editOrderNumber();
    fireEvent.click(screen.getByRole('button', { name: '生成订单号' }));
    await screen.findByDisplayValue('812345678');
    finishOrderNumberEdit();
    await act(async () => { resolveRead(await response(order)); });
    expect(screen.getByText('812345678')).toBeInTheDocument();
    expect(screen.queryByText(order.order_id)).not.toBeInTheDocument();
});

test('a conflict keeps the saved number and the unsaved draft and shows the server error', async () => {
    setup({ onGenerate: () => response(null, 409, '原单号已变更，请刷新后重试') });
    renderOrder();
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue(cargo.transfer_id), { target: { value: 'MANUAL-DRAFT' } });
    fireEvent.click(within(row).getByRole('button', { name: '生成原单号' }));
    expect(await screen.findByText('原单号已变更，请刷新后重试')).toBeInTheDocument();
    expect(within(row).getByDisplayValue('MANUAL-DRAFT')).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: /取\s*消/ }));
    expect(within(row).getByText(cargo.transfer_id)).toBeInTheDocument();
});

test.each(['admin', 'store_manager', 'salesperson', 'clerk'])('%s can generate numbers', async role => {
    setup({ roles: [role] });
    renderOrder();
    await screen.findByText(order.order_id);
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    editOrderNumber();
    expect(screen.getByRole('button', { name: '生成订单号' })).not.toBeDisabled();
    finishOrderNumberEdit();
    const cargoRow = screen.getByText(cargo.transfer_id).closest('tr');
    fireEvent.click(within(cargoRow).getByRole('button', { name: /编\s*辑/ }));
    expect(screen.getAllByRole('button', { name: '生成原单号' })).toHaveLength(1);
    expect(within(cargoRow).getByRole('button', { name: '生成原单号' })).not.toBeDisabled();
});

test('finance cannot generate even with permissive edit policy; manual input remains available', async () => {
    setup({ roles: ['finance'] });
    renderOrder();
    await screen.findByText(order.order_id);
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
});

test('field policies and box shipment history protect generation while ordinary cargo keeps its existing rules', async () => {
    setup({
        orderOverrides: { edit_policy: { ...policy, order_fields: false } },
        cargos: [{ ...cargo, status: 1 }, { ...box, identity_editable: false }],
    });
    renderOrder();
    const cargoRow = (await screen.findByText(cargo.transfer_id)).closest('tr');
    expect(screen.queryByRole('button', { name: '生成订单号' })).not.toBeInTheDocument();
    fireEvent.click(within(cargoRow).getByRole('button', { name: /编\s*辑/ }));
    expect(within(cargoRow).getByRole('button', { name: '生成原单号' })).toBeInTheDocument();
    fireEvent.click(within(cargoRow).getByRole('button', { name: /取\s*消/ }));
    const boxRow = screen.getByText(box.transfer_id).closest('tr');
    fireEvent.click(within(boxRow).getByRole('button', { name: /编\s*辑/ }));
    expect(within(boxRow).queryByRole('button', { name: '生成原单号' })).not.toBeInTheDocument();
});

test('manual order and original number edits still save without generation or collision checks', async () => {
    setup();
    renderOrder();
    const orderNumber = await screen.findByText(order.order_id);
    const orderCell = orderNumber.closest('td');
    fireEvent.click(orderNumber.querySelector('.ant-typography-edit'));
    const orderInput = await within(orderCell).findByRole('textbox');
    fireEvent.change(orderInput, { target: { value: 'MANUAL-ORDER' } });
    fireEvent.keyDown(orderInput, { key: 'Enter', keyCode: 13, code: 'Enter' });
    fireEvent.keyUp(orderInput, { key: 'Enter', keyCode: 13, code: 'Enter' });
    await screen.findByText('MANUAL-ORDER');
    const row = (await screen.findByText(cargo.transfer_id)).closest('tr');
    fireEvent.click(within(row).getByRole('button', { name: /编\s*辑/ }));
    fireEvent.change(within(row).getByDisplayValue(cargo.transfer_id), { target: { value: box.transfer_id } });
    fireEvent.click(within(row).getByRole('button', { name: /保\s*存/ }));
    await waitFor(() => {
        const put = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/cargo/cargo-1') && options?.method === 'PUT');
        expect(JSON.parse(put[1].body)).toEqual({ transfer_id: box.transfer_id });
    });
    expect(generationCalls()).toHaveLength(0);
});

test('a late generation response cannot overwrite the next order after navigation', async () => {
    let resolve;
    setup({ onGenerate: () => new Promise(done => { resolve = done; }) });
    renderOrder();
    await screen.findByText(order.order_id);
    editOrderNumber();
    fireEvent.click(screen.getByRole('button', { name: '生成订单号' }));
    fireEvent.click(screen.getByRole('button', { name: '切换订单' }));
    await screen.findByText('NEXT-ORDER');
    await act(async () => { resolve(await response({ order_id: '812345678' })); });
    expect(screen.getByText('NEXT-ORDER')).toBeInTheDocument();
    expect(screen.queryByText('812345678')).not.toBeInTheDocument();
});
