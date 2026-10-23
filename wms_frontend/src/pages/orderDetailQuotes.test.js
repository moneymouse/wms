import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import OrderDetail from './orderDetail';

jest.mock('antd/es/input/Input', () => ({
    __esModule: true,
    default: jest.requireActual('antd').Input,
}));
jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/BoxAssignmentModal', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/transportation', () => () => null);

const quoteHistory = [
    {
        id: 2, version_no: 2, transportation_name: 'DHL', unit_price: 12,
        surcharge: 8, weight_snapshot: 10, receivable_amount: 128,
        validity_status: 'effective', is_final: true, is_effective: true,
        quoter_name: '订单业务员', quote_remark: '包含偏远附加费\n按实际重量结算',
    },
    {
        id: 1, version_no: 1, transportation_name: '历史渠道', unit_price: 10,
        surcharge: 0, weight_snapshot: 10, receivable_amount: 100,
        validity_status: 'superseded', is_final: false,
        quoter_name: '订单业务员', quote_remark: null,
    },
];

function renderOrder(roles = ['salesperson'], userId = 99, quotes = quoteHistory) {
    const payload = window.btoa(JSON.stringify({ user_id: userId, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
    const order = {
        uid: 'order-uid', order_id: 'ORDER-1', transportation: 'DHL',
        salesman: { id: 7, name: '订单业务员' }, customer_ids: [],
    };
    global.fetch = jest.fn((rawUrl, options) => {
        const url = String(rawUrl);
        let data = [];
        if (url.endsWith('/salesman')) data = order.salesman;
        else if (url.endsWith('/orders/order-uid')) data = order;
        else if (url.endsWith('/quotes')) data = options?.method === 'POST' ? {} : quotes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data }) });
    });
    return render(<MemoryRouter initialEntries={['/orders/order-uid']}>
        <Routes><Route path="/orders/:order_id" element={<OrderDetail />} /></Routes>
    </MemoryRouter>);
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});

afterEach(() => jest.restoreAllMocks());

test.each(['salesperson', 'admin', 'store_manager', 'finance'])('%s can read another owner’s quote versions and remarks without editing', async role => {
    renderOrder([role]);
    await screen.findByText('ORDER-1');
    fireEvent.click(screen.getByRole('button', { name: /报价版本/ }));
    const dialog = await screen.findByRole('dialog', { name: /报价版本 ORDER-1/ });
    expect(await within(dialog).findByText('包含偏远附加费 按实际重量结算')).toBeInTheDocument();
    expect(within(dialog).getByText('历史渠道').closest('tr')).toHaveTextContent('-');
    expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('spinbutton')).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: '提交报价' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /打印报价单/ })).not.toBeDisabled();
    fireEvent.click(within(dialog).getByRole('button', { name: /关\s*闭/ }));
    expect(global.fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

test('the order owner can still submit a new quote and view previous remarks', async () => {
    renderOrder(['salesperson'], 7);
    fireEvent.click(await screen.findByRole('button', { name: /dollar\s*报价$/ }));
    const dialog = await screen.findByRole('dialog', { name: /订单报价 ORDER-1/ });
    expect(await within(dialog).findByText('包含偏远附加费 按实际重量结算')).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText('每公斤单价 (CNY/kg)'), { target: { value: '15' } });
    fireEvent.change(within(dialog).getByLabelText('报价说明'), { target: { value: '新报价说明' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '提交报价' }));
    await waitFor(() => {
        const request = global.fetch.mock.calls.find(([url, options]) => String(url).endsWith('/quotes') && options?.method === 'POST');
        expect(request).toBeDefined();
        expect(JSON.parse(request[1].body)).toEqual({ unit_price: 15, surcharge: 0, quote_remark: '新报价说明' });
    });
});

test('a read-only viewer can open an order with no quote history', async () => {
    renderOrder(['finance'], 99, []);
    await screen.findByText('ORDER-1');
    fireEvent.click(screen.getByRole('button', { name: /报价版本/ }));
    const dialog = await screen.findByRole('dialog', { name: /报价版本 ORDER-1/ });
    expect(within(dialog).getByText('暂无最终采纳报价')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /打印报价单/ })).toBeDisabled();
    expect(within(dialog).queryByRole('button', { name: '提交报价' })).not.toBeInTheDocument();
});

test('roles without quote access do not receive the quote history entry', async () => {
    renderOrder(['clerk']);
    await screen.findByText('ORDER-1');
    expect(screen.queryByRole('button', { name: /报价版本|dollar\s*报价$/ })).not.toBeInTheDocument();
    expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/quotes'))).toBe(false);
});
