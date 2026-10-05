import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
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

    global.fetch = jest.fn(rawUrl => {
        const url = String(rawUrl);
        if (url.includes('/orders/order-uid/cargo?')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    code: 200,
                    data: [{
                        uid: 'box-uid',
                        packing_list_uid: 'packing-list-uid',
                        tag: 'VERY-LONG-PACKING-LIST-MARK-001_1',
                        status: 0,
                    }],
                }),
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
                        order_id: 'ORDER-1',
                        customer_ids: null,
                    },
                }),
            });
        }
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ code: 200, data: [] }),
        });
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('a long packing-list mark wraps inside its cell and opens the corresponding detail page', async () => {
    render(
        <MemoryRouter initialEntries={['/orders/order-uid']}>
            <Routes>
                <Route path="/orders/:order_id" element={<OrderDetail />} />
                <Route path="/packing-lists/:uid" element={<div>装箱单详情目标页</div>} />
            </Routes>
        </MemoryRouter>
    );

    const markButton = await screen.findByRole('button', { name: 'VERY-LONG-PACKING-LIST-MARK-001_1' });
    expect(markButton).toHaveStyle({
        width: '100%',
        maxWidth: '100%',
        whiteSpace: 'normal',
        overflowWrap: 'anywhere',
        wordBreak: 'break-all',
    });

    fireEvent.click(markButton);

    expect(await screen.findByText('装箱单详情目标页')).toBeInTheDocument();
});
