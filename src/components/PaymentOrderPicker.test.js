import React, { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import PaymentOrderPicker from './PaymentOrderPicker';
import { financeRequest } from '../common/financeApi';

jest.mock('../common/financeApi', () => ({ financeRequest: jest.fn() }));

const firstOrder = {
    order_uid: 'order-1', order_number: 'WMS-1001', create_date: '2026-10-06 10:30:00',
    customer_name: '客户甲', receiver: 'Alice', country: '美国', tag_all: 'MARK-101',
    transportation: 'DHL', cn_name: '棉质衬衫', en_name: 'SHIRT', city: 'Seattle',
    address: '123 Main St', cargo_count: 2, total_weight: '23.50',
};
const secondOrder = { ...firstOrder, order_uid: 'order-2', order_number: 'WMS-1002', receiver: 'Bob' };
const list = (items, total = items.length) => ({ items, total });
const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
    return { promise, resolve, reject };
};
function ControlledPicker({ initialValue = [], onChange = jest.fn(), ...props }) {
    const [value, setValue] = useState(initialValue);
    return <PaymentOrderPicker {...props} value={value} onChange={keys => { setValue(keys); onChange(keys); }} />;
}
function checkboxFor(orderNumber) {
    const row = screen.getByRole('row', { name: new RegExp(orderNumber) });
    return within(row).getByRole('checkbox');
}
function submitSearch(keyword) {
    const search = screen.getByRole('searchbox', { name: '搜索参考订单' });
    fireEvent.change(search, { target: { value: keyword } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
}

beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }),
    });
    financeRequest.mockResolvedValue(list([firstOrder]));
});

test('loads recent customer orders and reuses the order list fields without leaving the form', async () => {
    render(<PaymentOrderPicker customerId={7} />);
    expect(await screen.findByText('WMS-1001')).toBeInTheDocument();
    expect(financeRequest).toHaveBeenCalledWith('/payment-options/orders', {
        params: { customer_id: '7', q: '', p: 1, s: 10 }, signal: expect.any(AbortSignal),
    });
    for (const value of ['2026-10-06 10:30:00', '客户甲', 'Alice', '美国', 'MARK-101', 'DHL', '棉质衬衫', '123 Main St', '23.50']) {
        expect(screen.getByText(value)).toBeInTheDocument();
    }
    expect(screen.getByRole('columnheader', { name: '箱数' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '总重量(kg)' })).toBeInTheDocument();
    expect(screen.getByText(/按创建时间倒序/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'WMS-1001' })).not.toBeInTheDocument();
});

test('keeps orders selected across server pages and allows removing or clearing them', async () => {
    const onChange = jest.fn();
    financeRequest.mockImplementation((_path, { params }) => Promise.resolve(list(params.p === 1 ? [firstOrder] : [secondOrder], 12)));
    render(<ControlledPicker customerId={7} onChange={onChange} />);
    await screen.findByText('WMS-1001');
    fireEvent.click(checkboxFor('WMS-1001'));
    expect(onChange).toHaveBeenLastCalledWith(['order-1']);
    fireEvent.click(screen.getByTitle('2'));
    await screen.findByText('WMS-1002');
    expect(financeRequest).toHaveBeenLastCalledWith('/payment-options/orders', expect.objectContaining({ params: { customer_id: '7', q: '', p: 2, s: 10 } }));
    expect(screen.getByRole('button', { name: '移除参考订单 WMS-1001' })).toBeInTheDocument();
    fireEvent.click(checkboxFor('WMS-1002'));
    expect(onChange).toHaveBeenLastCalledWith(['order-1', 'order-2']);
    fireEvent.click(screen.getByRole('button', { name: '移除参考订单 WMS-1001' }));
    expect(onChange).toHaveBeenLastCalledWith(['order-2']);
    fireEvent.click(screen.getByRole('button', { name: '清空选择' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
    expect(screen.queryByText(/已选择/)).not.toBeInTheDocument();
});

test('searches operational fields on the server from page one and clears the query', async () => {
    financeRequest.mockResolvedValue(list([firstOrder], 21));
    render(<PaymentOrderPicker customerId={7} />);
    await screen.findByText('WMS-1001');
    fireEvent.click(screen.getByTitle('2'));
    await waitFor(() => expect(financeRequest).toHaveBeenLastCalledWith('/payment-options/orders', expect.objectContaining({ params: expect.objectContaining({ p: 2 }) })));
    submitSearch('MARK-101');
    await waitFor(() => expect(financeRequest).toHaveBeenLastCalledWith('/payment-options/orders', expect.objectContaining({ params: { customer_id: '7', q: 'MARK-101', p: 1, s: 10 } })));
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索参考订单' }), { target: { value: '' } });
    await waitFor(() => expect(financeRequest).toHaveBeenLastCalledWith('/payment-options/orders', expect.objectContaining({ params: { customer_id: '7', q: '', p: 1, s: 10 } })));
});

test('changing customers clears selection and search and ignores the previous customer response', async () => {
    const pending = deferred();
    const onChange = jest.fn();
    financeRequest.mockImplementation((_path, { params }) => params.customer_id === '7' ? pending.promise : Promise.resolve(list([secondOrder])));
    const view = render(<ControlledPicker customerId={7} initialValue={['order-1']} selectedOrders={[{ order_uid: 'order-1', order_number: 'WMS-1001' }]} onChange={onChange} />);
    expect(screen.getByRole('button', { name: '移除参考订单 WMS-1001' })).toBeInTheDocument();
    submitSearch('MARK-101');
    view.rerender(<ControlledPicker customerId={8} initialValue={['order-1']} selectedOrders={[{ order_uid: 'order-1', order_number: 'WMS-1001' }]} onChange={onChange} />);
    await screen.findByText('WMS-1002');
    expect(onChange).toHaveBeenLastCalledWith([]);
    expect(screen.getByRole('searchbox', { name: '搜索参考订单' })).toHaveValue('');
    expect(financeRequest).toHaveBeenLastCalledWith('/payment-options/orders', expect.objectContaining({ params: { customer_id: '8', q: '', p: 1, s: 10 } }));
    await act(async () => pending.resolve(list([firstOrder])));
    expect(screen.queryByText('WMS-1001')).not.toBeInTheDocument();
    expect(screen.getByText('WMS-1002')).toBeInTheDocument();
});

test('retains selected order labels after a lookup failure and supports retry', async () => {
    financeRequest.mockRejectedValueOnce(new Error('订单服务暂不可用')).mockResolvedValueOnce(list([firstOrder]));
    render(<ControlledPicker customerId={7} initialValue={['order-1']} selectedOrders={[{ order_uid: 'order-1', order_number: 'WMS-1001' }]} />);
    expect(await screen.findByText('订单服务暂不可用')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '移除参考订单 WMS-1001' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^重\s*试$/ }));
    await screen.findByText('Alice');
    expect(screen.queryByText('订单服务暂不可用')).not.toBeInTheDocument();
    expect(checkboxFor('WMS-1001')).toBeChecked();
});

test('requires a customer before loading and disables selection while saving', async () => {
    const view = render(<PaymentOrderPicker />);
    expect(screen.getByText('请先选择客户')).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: '搜索参考订单' })).toBeDisabled();
    expect(financeRequest).not.toHaveBeenCalled();
    view.rerender(<PaymentOrderPicker customerId={7} />);
    await screen.findByText('WMS-1001');
    view.rerender(<PaymentOrderPicker customerId={7} disabled value={['order-1']} />);
    expect(checkboxFor('WMS-1001')).toBeDisabled();
    expect(screen.getByRole('button', { name: '清空选择' })).toBeDisabled();
    expect(screen.getByRole('searchbox', { name: '搜索参考订单' })).toBeDisabled();
});
