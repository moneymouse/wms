import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);

const order = {
    uid: 'order-uid', order_id: 'ORDER-1', transportation: 'DHL',
    salesman: { id: 7, name: 'Salesperson A' }, customer_ids: [42], customer_name: 'Customer A',
};
const contact = { phone: '13800138000', wechat: 'customer-a-wechat' };
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
const deferred = () => {
    let resolve;
    const promise = new Promise(complete => { resolve = complete; });
    return { promise, resolve };
};

function setJwt(payload = { roles: ['salesperson'] }) {
    window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: 7, ...payload }))}.signature`);
}

function mockApi({ orderData = order, contactResponse, orderResponse, cargoResponse, nextCargo = [], nextOrder = null } = {}) {
    let currentOrder = orderData;
    global.fetch = jest.fn(async (rawUrl, options = {}) => {
        const pathname = new URL(rawUrl, 'http://localhost').pathname;
        if (pathname.endsWith('/customer-contact')) {
            if (pathname.includes('/orders/next-order/')) return response({ phone: '13900139000', wechat: 'customer-b-wechat' });
            return contactResponse ? contactResponse() : response(contact);
        }
        if (pathname.endsWith('/salesman')) {
            if (options.method === 'PUT') {
                currentOrder = { ...currentOrder, salesman: null, salesman_id: null };
                return response(null);
            }
            return response(pathname.includes('/orders/next-order/') ? nextOrder?.salesman : currentOrder.salesman);
        }
        if (pathname.endsWith('/orders/order-uid')) return orderResponse ? orderResponse() : response(currentOrder);
        if (pathname.endsWith('/orders/next-order')) return response(nextOrder);
        if (pathname.endsWith('/orders/order-uid/cargo')) return cargoResponse ? cargoResponse() : response([]);
        if (pathname.endsWith('/orders/next-order/cargo')) return response(nextCargo);
        return response([]);
    });
}

function NextOrderButton() {
    const navigate = useNavigate();
    return <button onClick={() => navigate('/orders/next-order')}>Next order</button>;
}

function renderOrder() {
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}>
        <NextOrderButton />
        <Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes>
    </MemoryRouter>);
}

function contactCalls() {
    return global.fetch.mock.calls.filter(([url]) => String(url).includes('/customer-contact'));
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

test.each([
    [{ roles: ['salesperson'] }, 7],
    [{ role: 'salesperson' }, 7],
    [{ roles: ['admin'] }, 99],
    [{ roles: ['store_manager'] }, 99],
    [{ roles: ['salesperson', 'admin'] }, 99],
    [{ roles: ['salesperson'], role: 'store_manager' }, 99],
])('%j can view contacts with assigned salesperson %s', async (payload, salesmanId) => {
    setJwt(payload);
    mockApi({ orderData: { ...order, salesman: { id: salesmanId } } });
    renderOrder();
    expect(await screen.findByText(contact.phone)).toBeInTheDocument();
    expect(screen.getByText(contact.wechat)).toBeInTheDocument();
    expect(contactCalls()).toHaveLength(1);
    expect(new URL(contactCalls()[0][0], 'http://localhost').pathname).toMatch(/\/orders\/order-uid\/customer-contact$/);
    expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/customer_detail/'))).toBe(false);
});

test.each([
    ['salesperson', { id: 99 }],
    ['salesperson', null],
    ['clerk', { id: 7 }],
    ['finance', { id: 7 }],
])('%s cannot read contacts with assigned salesperson %j', async (role, salesman) => {
    setJwt({ roles: [role] });
    mockApi({ orderData: { ...order, salesman } });
    renderOrder();
    await screen.findByText('DHL');
    expect(screen.queryByText('客户手机号')).not.toBeInTheDocument();
    expect(screen.queryByText('客户微信')).not.toBeInTheDocument();
    expect(contactCalls()).toHaveLength(0);
});

test('contact requests wait until the order and its ownership have loaded', async () => {
    const pendingOrder = deferred();
    mockApi({ orderResponse: () => pendingOrder.promise });
    renderOrder();
    await screen.findByDisplayValue('Salesperson A');
    expect(contactCalls()).toHaveLength(0);
    expect(screen.queryByText('客户手机号')).not.toBeInTheDocument();
    await act(async () => { pendingOrder.resolve(response(order)); });
    expect(await screen.findByText(contact.phone)).toBeInTheDocument();
});

test('orders without a customer do not request contact information', async () => {
    mockApi({ orderData: { ...order, customer_ids: [] } });
    renderOrder();
    await screen.findByText('DHL');
    expect(contactCalls()).toHaveLength(0);
    expect(screen.queryByText(contact.phone)).not.toBeInTheDocument();
});

test('denied contact responses do not display sensitive fields', async () => {
    const pendingContact = deferred();
    mockApi({ contactResponse: () => pendingContact.promise });
    renderOrder();
    await waitFor(() => expect(contactCalls()).toHaveLength(1));
    await act(async () => { pendingContact.resolve({ ok: false, json: async () => ({ code: 403, data: contact }) }); });
    expect(screen.queryByText(contact.phone)).not.toBeInTheDocument();
    expect(screen.queryByText(contact.wechat)).not.toBeInTheDocument();
});

test('removing the assigned salesperson clears contact access and ignores the pending response', async () => {
    const pendingContact = deferred();
    mockApi({ contactResponse: () => pendingContact.promise });
    renderOrder();
    await waitFor(() => expect(contactCalls()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: /^编\s*辑$/ }));
    fireEvent.click(screen.getByRole('button', { name: /^移\s*除$/ }));
    await waitFor(() => expect(screen.queryByText('客户手机号')).not.toBeInTheDocument());
    await act(async () => { pendingContact.resolve(response(contact)); });
    expect(screen.queryByText(contact.phone)).not.toBeInTheDocument();
    expect(screen.queryByText(contact.wechat)).not.toBeInTheDocument();
});

test('changing orders replaces contacts and ignores an earlier pending response', async () => {
    const pendingContact = deferred();
    mockApi({
        contactResponse: () => pendingContact.promise,
        nextOrder: { ...order, uid: 'next-order', order_id: 'ORDER-2', customer_ids: [43] },
    });
    renderOrder();
    await waitFor(() => expect(contactCalls()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'Next order' }));
    expect(await screen.findByText('13900139000')).toBeInTheDocument();
    await act(async () => { pendingContact.resolve(response(contact)); });
    expect(screen.queryByText(contact.phone)).not.toBeInTheDocument();
    expect(screen.queryByText(contact.wechat)).not.toBeInTheDocument();
    expect(screen.getByText('customer-b-wechat')).toBeInTheDocument();
});

test('changing orders replaces cargo and ignores the earlier pending cargo response', async () => {
    const pendingCargo = deferred();
    mockApi({
        cargoResponse: () => pendingCargo.promise,
        nextOrder: { ...order, uid: 'next-order', order_id: 'ORDER-2', customer_ids: [43] },
        nextCargo: [{ uid: 'next-cargo', transfer_id: 'NEXT-CARGO', status: 0, weight: 2 }],
    });
    renderOrder();
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/orders/order-uid/cargo?'))).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Next order' }));
    expect(await screen.findByText('NEXT-CARGO')).toBeInTheDocument();
    await act(async () => { pendingCargo.resolve(response([{ uid: 'old-cargo', transfer_id: 'OLD-CARGO', status: 0, weight: 1 }])); });
    expect(screen.queryByText('OLD-CARGO')).not.toBeInTheDocument();
    expect(screen.getByText('NEXT-CARGO')).toBeInTheDocument();
});
