import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.sessionStorage.setItem('wms:tour-flow:7', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'quote',
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
    global.fetch = jest.fn(url => Promise.resolve({
        ok: true,
        json: () => {
            if (url.includes('/salesman')) {
                return Promise.resolve({ code: 200, data: { id: 99, name: '其他业务员' } });
            }
            if (url.includes('/users/salespersons') || url.includes('/customs-codes')) {
                return Promise.resolve({ code: 200, data: [] });
            }
            if (url.includes('/cargo?')) {
                return Promise.resolve({ code: 200, data: [] });
            }
            return Promise.resolve({
                code: 200,
                data: {
                    uid: 'order-uid',
                    order_id: 'ORDER-1',
                    transportation: '',
                    salesman: { id: 99, name: '其他业务员' },
                },
            });
        },
    }));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('an ineligible quote workflow returns to order selection so the user can continue', async () => {
    render(
        <MemoryRouter initialEntries={['/orders/order-uid']}>
            <Routes>
                <Route path="/orders/:order_id" element={<OrderDetail />} />
                <Route path="/orders" element={<div>订单列表页</div>} />
            </Routes>
        </MemoryRouter>
    );

    expect(await screen.findByText('订单列表页')).toBeInTheDocument();
    await waitFor(() => expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:7'))).toMatchObject({
        stage: 'select-quote-order',
    }));
});
