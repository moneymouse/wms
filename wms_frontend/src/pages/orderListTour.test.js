import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import OrderList from './orderList';

jest.mock('../components/ExportButton', () => function MockExportButton() {
    return null;
});

jest.mock('../components/FeatureTour', () => function MockFeatureTour({ forceAutoStart, steps }) {
    return forceAutoStart ? (
        <div>
            <div>{steps[0].title}</div>
            <div>{steps[0].description}</div>
        </div>
    ) : null;
});

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    window.sessionStorage.setItem('wms:tour-flow:7', JSON.stringify({
        campaignId: 'cost-quote-receipt',
        stage: 'select-quote-order',
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
    global.fetch = jest.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
            data: [{ uid: 'order-uid', order_id: 'ORDER-1' }],
            total: 1,
        }),
    }));
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('selecting an order advances the first-time workflow to quote before navigation', async () => {
    render(
        <MemoryRouter initialEntries={['/orders']}>
            <Routes>
                <Route path="/orders" element={<OrderList />} />
                <Route path="/orders/:orderId" element={<div>订单详情页</div>} />
            </Routes>
        </MemoryRouter>
    );

    expect(await screen.findByText('请选择由你负责的订单')).toBeInTheDocument();
    expect(screen.getByText('由你负责的订单', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('订单号/客户名/收件人名/业务员/国家')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'ORDER-1' }));

    expect(await screen.findByText('订单详情页')).toBeInTheDocument();
    await waitFor(() => expect(JSON.parse(window.sessionStorage.getItem('wms:tour-flow:7'))).toMatchObject({
        stage: 'quote',
    }));
});
