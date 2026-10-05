import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
            if (url.includes('/users/salespersons') || url.includes('/customs-codes') || url.includes('/transportation-modes')) {
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

test('an order with receipt history permits ordinary editing and re-quoting', async () => {
    window.sessionStorage.clear();
    global.fetch = jest.fn(url => Promise.resolve({
        ok: true,
        json: () => {
            if (url.includes('/salesman')) {
                return Promise.resolve({ code: 200, data: { id: 7, name: '业务员' } });
            }
            if (url.includes('/users/salespersons') || url.includes('/customs-codes') || url.includes('/transportation-modes')) {
                return Promise.resolve({ code: 200, data: [] });
            }
            if (url.includes('/cargo?')) {
                return Promise.resolve({
                    code: 200,
                    data: [{
                        uid: 'cargo-1',
                        transfer_id: 'ORIG-1',
                        waybill_id: '',
                        tag: 'TAG-1',
                        count: 1,
                        real_en_name: 'SHOES',
                        weight: 10.5,
                        price: 1,
                        status: 0,
                    }],
                });
            }
            if (url.includes('/quotes')) {
                return Promise.resolve({
                    code: 200,
                    data: [{
                        id: 1,
                        version_no: 1,
                        transportation_name: '历史渠道',
                        unit_price: 12,
                        surcharge: 0,
                        weight_snapshot: 10.5,
                        receivable_amount: 132,
                        validity_status: 'effective',
                        is_final: true,
                        is_effective: true,
                        quoter_name: '业务员',
                    }],
                });
            }
            return Promise.resolve({
                code: 200,
                data: {
                    uid: 'order-uid',
                    order_id: 'ORDER-1',
                    transportation: '',
                    salesman: { id: 7, name: '业务员' },
                    customer_ids: [],
                    financial_lock: { active: true, has_history: true },
                },
            });
        },
    }));

    render(
        <MemoryRouter initialEntries={['/orders/order-uid']}>
            <Routes>
                <Route path="/orders/:order_id" element={<OrderDetail />} />
            </Routes>
        </MemoryRouter>
    );

    expect(await screen.findByText('订单详情/Order Detail')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '解锁订单' })).not.toBeInTheDocument();
    const quoteButton = await screen.findByRole('button', { name: /dollar\s*报价/ });
    expect(quoteButton).not.toBeDisabled();
    fireEvent.click(quoteButton);
    expect(await screen.findByRole('dialog', { name: /订单报价/ })).toBeInTheDocument();
    expect(await screen.findByText('历史渠道')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '提交报价' })).not.toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(screen.getByRole('button', { name: /添\s*加/ })).not.toBeDisabled();
    expect(screen.getByRole('button', { name: /从装箱单分配/ })).not.toBeDisabled();
    expect(await screen.findByRole('button', { name: '移除' })).not.toBeDisabled();

    const editButtons = screen.getAllByRole('button', { name: /编\s*辑/ });
    fireEvent.click(editButtons[editButtons.length - 1]);
    expect(screen.getByDisplayValue('ORIG-1')).toBeInTheDocument();
    expect(screen.getByDisplayValue('10.5')).toBeInTheDocument();
});
