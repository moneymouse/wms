import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({ __esModule: true, default: jest.requireActual('antd').Input }));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);
jest.mock('../components/OrderSupplierCosts', () => ({ orderUid }) => <div data-testid="supplier-costs">成本归属 {orderUid}</div>);

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
    global.fetch = jest.fn(async rawUrl => ({ ok: true, json: async () => ({ code: 200,
        data: new URL(rawUrl, 'http://localhost').pathname.endsWith('/orders/order-uid')
            ? { uid: 'order-uid', order_id: 'ORDER-1', edit_policy: {} } : [],
    }) }));
});

afterEach(() => jest.restoreAllMocks());

test.each(['admin', 'clerk', 'finance'])('%s can see supplier costs on the loaded order', async role => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ role, user_id: 7 }))}.signature`);
    render(<MemoryRouter initialEntries={['/orders/order-uid']}><Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes></MemoryRouter>);
    expect(await screen.findByTestId('supplier-costs')).toHaveTextContent('成本归属 order-uid');
});

test.each(['salesperson', 'store_manager'])('%s cannot see supplier costs', async role => {
    localStorage.setItem('jwt', `header.${btoa(JSON.stringify({ role, user_id: 7 }))}.signature`);
    render(<MemoryRouter initialEntries={['/orders/order-uid']}><Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes></MemoryRouter>);
    await screen.findAllByText('ORDER-1');
    expect(screen.queryByTestId('supplier-costs')).not.toBeInTheDocument();
});
