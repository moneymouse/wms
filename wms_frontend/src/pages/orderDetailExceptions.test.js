import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);
jest.mock('../components/OrderExceptionRegistration', () => ({ open, order }) => open ? <span>异常登记关联 {order.uid}</span> : null);
jest.mock('../components/OrderHistoryDrawer', () => ({ open, orderUid }) => open ? <span>修改历史关联 {orderUid}</span> : null);
const order = { uid: 'order-1', order_id: 'ORDER-1', transportation: 'DHL', salesman_id: 7, salesman: { id: 7, name: '业务员甲' } };
const response = data => ({ ok: true, json: async () => ({ code: 200, data }) });
beforeEach(() => {
    localStorage.clear(); sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    global.fetch = jest.fn(async rawUrl => {
        const path = new URL(rawUrl, 'http://localhost').pathname;
        if (path === '/api/orders/order-1') return response(order);
        if (path === '/api/orders/order-1/salesman') return response(order.salesman);
        return response([]);
    });
});
afterEach(() => jest.restoreAllMocks());
function showOrder(role, userId = 7) {
    localStorage.setItem('jwt', `h.${btoa(JSON.stringify({ user_id: userId, roles: [role] }))}.s`);
    return render(<MemoryRouter initialEntries={['/orders/order-1']}><Routes>
        <Route path="/orders/:order_id" element={<OrderDetail />} />
    </Routes></MemoryRouter>);
}

test.each(['admin', 'clerk', 'salesperson'])('%s can open registration for the current order', async role => {
    showOrder(role); fireEvent.click(await screen.findByRole('button', { name: '登记异常' }));
    expect(screen.getByText('异常登记关联 order-1')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test.each([['finance', 7], ['store_manager', 7], ['salesperson', 8]])('%s user %s cannot register outside the authorized role/owner scope', async (role, userId) => {
    showOrder(role, userId); await screen.findByText('DHL');
    expect(screen.queryByRole('button', { name: '登记异常' })).not.toBeInTheDocument();
});

test('admin keeps separate registration and modification-history entries for the current order', async () => {
    showOrder('admin');
    const register = await screen.findByRole('button', { name: '登记异常' });
    const history = screen.getByRole('button', { name: /修改历史/ });
    fireEvent.click(history);
    expect(screen.getByText('修改历史关联 order-1')).toBeInTheDocument();
    expect(screen.queryByText('异常登记关联 order-1')).not.toBeInTheDocument();
    fireEvent.click(register);
    expect(screen.getByText('异常登记关联 order-1')).toBeInTheDocument();
    expect(screen.getByText('修改历史关联 order-1')).toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test('store manager keeps modification history without gaining exception registration', async () => {
    showOrder('store_manager');
    fireEvent.click(await screen.findByRole('button', { name: /修改历史/ }));
    expect(screen.getByText('修改历史关联 order-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '登记异常' })).not.toBeInTheDocument();
});

test.each(['salesperson', 'clerk', 'finance'])('%s does not gain modification-history access from the new exception entry', async role => {
    showOrder(role); await screen.findByText('DHL');
    expect(screen.queryByRole('button', { name: /修改历史/ })).not.toBeInTheDocument();
});
