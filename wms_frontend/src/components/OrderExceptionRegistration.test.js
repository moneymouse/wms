import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OrderExceptionRegistration from './OrderExceptionRegistration';
import { fetchExceptionOrderCargos, registerOrderException, searchExceptionOrders } from '../common/orderExceptionApi';

jest.mock('../common/orderExceptionApi', () => ({
    ...jest.requireActual('../common/orderExceptionApi'),
    fetchExceptionOrderCargos: jest.fn(), registerOrderException: jest.fn(), searchExceptionOrders: jest.fn(),
}));
jest.mock('../config', () => ({ endpoint: '/api' }));
const order = { uid: 'order-1', order_id: 'ORDER-1' };
beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    searchExceptionOrders.mockResolvedValue([order]);
    fetchExceptionOrderCargos.mockResolvedValue([{ uid: 'cargo-1', origin_id: 'ORIGIN-1', waybill_id: 'WAY-1' }]);
    registerOrderException.mockResolvedValue({ uid: 'exception-1' });
});
afterEach(() => jest.restoreAllMocks());

test('fixed-order entry can register a package with its actual UID and reason', async () => {
    const onCreated = jest.fn();
    render(<OrderExceptionRegistration open order={order} onCreated={onCreated} />);
    const modal = await screen.findByRole('dialog', { name: '登记异常' });
    await waitFor(() => expect(fetchExceptionOrderCargos).toHaveBeenCalledWith('order-1', expect.anything()));
    await waitFor(() => expect(within(modal).getByRole('combobox', { name: '异常包裹' })).toBeEnabled());
    fireEvent.mouseDown(within(modal).getByRole('combobox', { name: '异常包裹' }));
    fireEvent.click(await screen.findByText('ORIGIN-1 / WAY-1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(within(modal).getByLabelText('异常理由'), { target: { value: '  包装破损  ' } });
    fireEvent.click(within(modal).getByRole('button', { name: '提交异常' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ uid: 'exception-1' }));
    expect(registerOrderException).toHaveBeenCalledWith({ order_uid: 'order-1', cargo_uid: 'cargo-1', reason: '包装破损', event_key: expect.any(String) });
    expect(searchExceptionOrders).not.toHaveBeenCalled();
});

test('page registration searches existing orders and defaults to the entire order', async () => {
    render(<OrderExceptionRegistration open onCreated={jest.fn()} />);
    fireEvent.change(await screen.findByLabelText('查找订单'), { target: { value: 'ORDER-1' } });
    fireEvent.click(screen.getByRole('button', { name: /查\s*找/ }));
    await waitFor(() => expect(searchExceptionOrders).toHaveBeenCalledWith('ORDER-1', expect.anything()));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '异常订单' }));
    fireEvent.click(await screen.findByText('ORDER-1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(screen.getByLabelText('异常理由'), { target: { value: '资料缺失' } });
    fireEvent.click(screen.getByRole('button', { name: '提交异常' }));
    await waitFor(() => expect(registerOrderException).toHaveBeenCalledTimes(1));
    expect(registerOrderException.mock.calls[0][0]).toEqual({ order_uid: 'order-1', reason: '资料缺失', event_key: expect.any(String) });
});

test('empty reason is rejected locally and retries retain the input and event key', async () => {
    registerOrderException.mockRejectedValueOnce(new Error('通知暂时失败，请重试')).mockResolvedValueOnce({ uid: 'ex-1' });
    render(<OrderExceptionRegistration open order={order} onCreated={jest.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: '提交异常' }));
    await screen.findByText('请填写异常理由');
    expect(registerOrderException).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('异常理由'), { target: { value: '货物破损' } });
    fireEvent.click(screen.getByRole('button', { name: '提交异常' }));
    await screen.findByText('通知暂时失败，请重试');
    await waitFor(() => expect(screen.getByRole('button', { name: '提交异常' })).not.toHaveClass('ant-btn-loading'));
    expect(screen.getByLabelText('异常理由')).toHaveValue('货物破损');
    fireEvent.click(screen.getByRole('button', { name: '提交异常' }));
    await waitFor(() => expect(registerOrderException).toHaveBeenCalledTimes(2));
    expect(registerOrderException.mock.calls[1][0]).toEqual(registerOrderException.mock.calls[0][0]);
});

test('canceling registration never submits or reads another exception history', async () => {
    const onCancel = jest.fn();
    render(<OrderExceptionRegistration open order={order} onCancel={onCancel} />);
    fireEvent.click(await screen.findByRole('button', { name: '取消' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(registerOrderException).not.toHaveBeenCalled();
});

test('a live tracking outage still permits manual registration for a local package', async () => {
    fetchExceptionOrderCargos.mockImplementation(jest.requireActual('../common/orderExceptionApi').fetchExceptionOrderCargos);
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ code: 500, msg: '物流查询失败',
        data: [{ uid: 'cargo-1', origin_id: 'INTERNAL-1', transfer_id: 'ORIGINAL-1', waybill_id: 'WAY-1' }] }) });
    render(<OrderExceptionRegistration open order={order} onCreated={jest.fn()} />);
    const parcel = await screen.findByRole('combobox', { name: '异常包裹' });
    await waitFor(() => expect(parcel).toBeEnabled());
    fireEvent.mouseDown(parcel);
    fireEvent.click(await screen.findByText('ORIGINAL-1 / WAY-1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(screen.getByLabelText('异常理由'), { target: { value: '客户反馈破损' } });
    fireEvent.click(screen.getByRole('button', { name: '提交异常' }));
    await waitFor(() => expect(registerOrderException).toHaveBeenCalledWith({ order_uid: 'order-1', cargo_uid: 'cargo-1', reason: '客户反馈破损', event_key: expect.any(String) }));
});

test('late same-order metadata retains the draft, while changing the order UID resets it', async () => {
    const onCreated = jest.fn();
    const { rerender } = render(<OrderExceptionRegistration open order={order} onCreated={onCreated} />);
    const parcel = await screen.findByRole('combobox', { name: '异常包裹' });
    await waitFor(() => expect(parcel).toBeEnabled());
    fireEvent.mouseDown(parcel);
    fireEvent.click(await screen.findByText('ORIGIN-1 / WAY-1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(screen.getByLabelText('异常理由'), { target: { value: '等待承运商确认' } });

    rerender(<OrderExceptionRegistration open order={{ ...order, order_id: 'ORDER-1-UPDATED', salesman: { id: 7, name: '业务员甲' } }} onCreated={onCreated} />);
    expect(screen.getByText('ORDER-1-UPDATED', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(screen.getByLabelText('异常理由')).toHaveValue('等待承运商确认');
    expect(screen.getByText('ORIGIN-1 / WAY-1', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    expect(fetchExceptionOrderCargos).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '提交异常' }));
    await waitFor(() => expect(registerOrderException).toHaveBeenCalledWith({ order_uid: 'order-1', cargo_uid: 'cargo-1', reason: '等待承运商确认', event_key: expect.any(String) }));
    await waitFor(() => expect(screen.getByRole('button', { name: '提交异常' })).not.toHaveClass('ant-btn-loading'));

    rerender(<OrderExceptionRegistration open order={{ uid: 'order-2', order_id: 'ORDER-2' }} onCreated={onCreated} />);
    expect(screen.getByLabelText('异常理由')).toHaveValue('');
    expect(screen.getByText('整张订单', { selector: '.ant-select-selection-placeholder' })).toBeInTheDocument();
    expect(screen.getByText('ORDER-2', { selector: '.ant-select-selection-item' })).toBeInTheDocument();
    await waitFor(() => expect(fetchExceptionOrderCargos).toHaveBeenLastCalledWith('order-2', expect.anything()));
});
