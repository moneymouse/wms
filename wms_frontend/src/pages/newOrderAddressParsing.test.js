import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { message } from 'antd';
import NewOrder from './newOrder';

jest.mock('../config', () => ({ endpoint: '/api' }));
jest.mock('../common/genWayBill', () => jest.fn());
jest.mock('../components/transportation', () => function MockTransportation() {
    return <div />;
});
jest.mock('../components/GoodName', () => function MockGoodName() {
    return <div />;
});

const FIELD_LABELS = {
    address: /详细地址\/Full Address/,
    receiver: /收货人\/Receiver$/,
    receiver_phone: /收货人电话\/Receiver Phone Number/,
    mail: /收货人邮箱\/Mail/,
    country: /国家\/Destination Country/,
    province: /州,省\/State,Province/,
    city: /城市\/City/,
    zip_code: /收件人邮编\/Zip Code/,
};
const getField = (name) => screen.getByLabelText(FIELD_LABELS[name]);
const getDraft = () => JSON.parse(localStorage.getItem('newOrderFormData'));
const parseCalls = () => global.fetch.mock.calls.filter(([url]) => url.endsWith('/orders/parse-address'));
const originalAddress = '10 MAIN STREET NEW YORK NY 10001 USA';
const parsedAddress = {
    country: 'US',
    province: 'NY',
    city: 'New York',
    address: '10 Main Street',
    zip_code: '10001',
    receiver: 'Jane Doe',
    receiver_phone: '+1 212 555 0100',
    mail: 'jane@example.com',
    warnings: [],
};

let pendingParse;
let messageApi;

function response(body, ok = true) {
    return { ok, json: async () => body };
}

async function renderOrder(draft = { address: originalAddress }) {
    localStorage.setItem('newOrderFormData', JSON.stringify(draft));
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><NewOrder /></MemoryRouter>);
    await waitFor(() => expect(getField('address')).toHaveValue(draft.address || ''));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/customer_list', expect.anything()));
}

async function finishParsing(data = parsedAddress) {
    await act(async () => pendingParse.resolve(response({ code: 200, data })));
}

beforeEach(() => {
    localStorage.clear();
    const payload = window.btoa(JSON.stringify({ user_id: 7, name: 'Salesperson' }));
    localStorage.setItem('jwt', `header.${payload}.signature`);
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: (query) => ({
            matches: false, media: query, onchange: null,
            addListener: () => {}, removeListener: () => {},
            addEventListener: () => {}, removeEventListener: () => {},
            dispatchEvent: () => false,
        }),
    });
    messageApi = Object.fromEntries(['error', 'warning', 'success', 'info'].map((key) => [key, jest.fn()]));
    jest.spyOn(message, 'useMessage').mockReturnValue([messageApi, null]);
    pendingParse = {};
    pendingParse.promise = new Promise((resolve, reject) => {
        pendingParse.resolve = resolve;
        pendingParse.reject = reject;
    });
    global.fetch = jest.fn((url) => {
        if (url.endsWith('/orders/parse-address')) return pendingParse.promise;
        if (url.endsWith('/create')) return Promise.resolve(response({ code: 200 }));
        return Promise.resolve(response({ code: 200, data: [] }));
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('shows an address parsing link below the input and enables it only for nonblank input', async () => {
    await renderOrder({});
    const addressItem = getField('address').closest('.ant-form-item');
    const button = within(addressItem).getByRole('button', { name: '解析地址' });
    expect(addressItem.querySelector('.ant-form-item-extra')).toContainElement(button);
    expect(button).toBeDisabled();
    fireEvent.change(getField('address'), { target: { value: '   ' } });
    expect(button).toBeDisabled();
    fireEvent.change(getField('address'), { target: { value: '  10 Main Street USA  ' } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    const [, request] = parseCalls()[0];
    expect(request).toEqual(expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
            'x-token': localStorage.getItem('jwt'),
            'x-time': expect.any(String),
            'Content-Type': 'application/json',
        }),
    }));
    expect(JSON.parse(request.body)).toEqual({ address: '10 MAIN STREET USA' });
    await finishParsing();
    expect(messageApi.success).toHaveBeenCalledWith('地址已解析并回填');
    expect(messageApi.warning).not.toHaveBeenCalled();
});

test.each([false, true])('preserves the detailed address while filling and saving other fields (response includes address: %s)', async (includesAddress) => {
    const quote = { unit_price: 12, surcharge: 8, quote_remark: 'Saved quote' };
    await renderOrder({ address: originalAddress, customer_name: 'Existing Customer', en_name: 'SHOES', quote });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    expect(screen.getByRole('button', { name: /解析中…/ })).toBeDisabled();
    const data = { ...parsedAddress };
    if (!includesAddress) delete data.address;
    await finishParsing(data);
    const expected = { ...data, country: 'USA', address: originalAddress };
    delete expected.warnings;
    Object.entries(expected).forEach(([name, value]) => expect(getField(name)).toHaveValue(value));
    expect(getDraft()).toEqual(expect.objectContaining({
        ...expected, customer_name: 'Existing Customer', en_name: 'SHOES', quote,
    }));
    expect(screen.getByRole('button', { name: '解析地址' })).toBeEnabled();
    expect(messageApi.success).toHaveBeenCalled();
});

test('fills corrected country and common postal province with a short city ambiguity warning', async () => {
    const address = 'CALLE MAYOR 10 ALICANTE 03001 SPIAN';
    const warning = '邮编对应多个城市';
    await renderOrder({
        address, country: 'USA', city: 'Existing City', province: 'Existing State',
        receiver: 'Existing Receiver',
    });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    await finishParsing({
        country: 'ES', city: 'Alicante', province: 'Comunitat Valenciana', zip_code: '03001',
        warnings: [warning],
    });

    const expected = {
        address, country: 'SPAIN', city: 'Alicante', province: 'Comunitat Valenciana',
        zip_code: '03001', receiver: 'Existing Receiver',
    };
    Object.entries(expected).forEach(([name, value]) => expect(getField(name)).toHaveValue(value));
    expect(getDraft()).toEqual(expect.objectContaining(expected));
    expect(messageApi.warning).toHaveBeenCalledWith(`已回填。${warning}`, 8);
    expect(messageApi.success).not.toHaveBeenCalled();
    expect(parseCalls()).toHaveLength(1);
    expect(JSON.parse(parseCalls()[0][1].body)).toEqual({ address });
});

test('persists the latest quote when it is edited while address parsing is pending', async () => {
    await renderOrder({
        address: originalAddress,
        quote: { unit_price: 12, surcharge: 8, quote_remark: 'Original quote' },
    });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    fireEvent.click(screen.getByRole('button', { name: /报价/ }));
    const price = await screen.findByLabelText('每公斤单价 (CNY/kg)');
    fireEvent.change(price, { target: { value: '23' } });
    fireEvent.change(screen.getByLabelText('报价说明'), { target: { value: 'Updated quote' } });
    fireEvent.click(screen.getByRole('button', { name: '保存报价' }));
    await waitFor(() => expect(getDraft().quote).toEqual({
        unit_price: 23, surcharge: 8, quote_remark: 'Updated quote',
    }));
    await finishParsing();
    expect(getDraft().quote).toEqual({ unit_price: 23, surcharge: 8, quote_remark: 'Updated quote' });
    expect(getDraft().city).toBe('New York');
});

test('does not launch a duplicate request while address parsing is pending', async () => {
    await renderOrder();
    const button = screen.getByRole('button', { name: '解析地址' });
    act(() => {
        fireEvent.click(button);
        fireEvent.click(button);
    });
    expect(parseCalls()).toHaveLength(1);
    await finishParsing();
});

test.each(['backend', 'network'])('preserves the form and allows retry after a %s error', async (failure) => {
    const draft = { address: originalAddress, receiver: 'Existing Receiver', city: 'Existing City' };
    await renderOrder(draft);
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    await act(async () => {
        if (failure === 'backend') {
            pendingParse.resolve(response({ code: 503, msg: '地址解析服务未配置' }, false));
        } else {
            pendingParse.reject(new Error('Network unavailable'));
        }
    });
    Object.entries(draft).forEach(([name, value]) => expect(getField(name)).toHaveValue(value));
    expect(getDraft()).toEqual(draft);
    expect(screen.getByRole('button', { name: '解析地址' })).toBeEnabled();
    expect(messageApi.error).toHaveBeenCalledWith(failure === 'backend'
        ? '地址解析服务未配置'
        : expect.stringContaining('地址解析失败'));
});

test('preserves existing fields when parsed values are empty, invalid, or unrecognized', async () => {
    const draft = {
        address: originalAddress, country: 'USA', province: 'Existing State', city: 'Existing City',
        receiver: 'Existing Receiver', receiver_phone: '555', mail: 'existing@example.com', zip_code: '01000',
    };
    await renderOrder(draft);
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    await finishParsing({
        country: 'ZZ', province: '', city: ' ', address: null, receiver: ' New Receiver ',
        receiver_phone: 12345, mail: '', zip_code: null, customer_name: 'Unexpected Customer', warnings: [],
    });
    Object.entries({ ...draft, receiver: 'New Receiver' }).forEach(([name, value]) => (
        expect(getField(name)).toHaveValue(value)
    ));
    expect(getDraft()).toEqual(expect.objectContaining({ ...draft, receiver: 'New Receiver' }));
    expect(getDraft().customer_name).toBeUndefined();
    expect(messageApi.warning).toHaveBeenCalledWith(expect.stringContaining('国家无法匹配，请手动选择'), 8);
});

test('shows backend warnings when no address fields can be filled', async () => {
    await renderOrder({ address: originalAddress, receiver: 'Existing Receiver' });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    await finishParsing({ address: '10 Main Street', warnings: ['请补充门牌号', '', null] });
    expect(getField('address')).toHaveValue(originalAddress);
    expect(getField('receiver')).toHaveValue('Existing Receiver');
    expect(messageApi.warning).toHaveBeenCalledWith('请补充门牌号', 8);
    expect(messageApi.success).not.toHaveBeenCalled();
});

test('keeps contact fields manually edited during parsing while filling unchanged fields', async () => {
    await renderOrder({ address: originalAddress, receiver: 'Existing Receiver' });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    fireEvent.change(getField('receiver'), { target: { value: 'Manual Receiver' } });
    await finishParsing();
    expect(getField('receiver')).toHaveValue('Manual Receiver');
    expect(getField('city')).toHaveValue('New York');
    expect(getDraft()).toEqual(expect.objectContaining({ receiver: 'Manual Receiver', city: 'New York' }));
    expect(messageApi.warning).toHaveBeenCalledWith(expect.stringContaining('已保留手动修改'), 8);
});

test('reports that current content was kept when every recognized field was manually changed', async () => {
    await renderOrder({ address: originalAddress, receiver: 'Existing Receiver', city: 'Existing City' });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    fireEvent.change(getField('receiver'), { target: { value: 'Manual Receiver' } });
    fireEvent.change(getField('city'), { target: { value: 'Manual City' } });
    await finishParsing({ receiver: 'Parsed Receiver', city: 'Parsed City' });
    expect(getField('receiver')).toHaveValue('Manual Receiver');
    expect(getField('city')).toHaveValue('Manual City');
    expect(messageApi.info).toHaveBeenCalledWith('已保留当前内容');
    expect(messageApi.success).not.toHaveBeenCalled();
});

test('ignores a pending result when the detailed address was changed', async () => {
    await renderOrder({ address: originalAddress, receiver: 'Existing Receiver' });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    fireEvent.change(getField('address'), { target: { value: '20 DIFFERENT STREET' } });
    await finishParsing();
    expect(getField('address')).toHaveValue('20 DIFFERENT STREET');
    expect(getField('receiver')).toHaveValue('Existing Receiver');
    expect(getField('city')).toHaveValue('');
    expect(getDraft()).toEqual(expect.objectContaining({ address: '20 DIFFERENT STREET', receiver: 'Existing Receiver' }));
});

test('invalidates a pending result after clearing even when the same address is entered again', async () => {
    await renderOrder();
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    const requestSignal = parseCalls()[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: /清空表单/ }));
    expect(requestSignal.aborted).toBe(true);
    expect(localStorage.getItem('newOrderFormData')).toBeNull();
    fireEvent.change(getField('address'), { target: { value: originalAddress } });
    await finishParsing();
    expect(getField('address')).toHaveValue(originalAddress);
    expect(getField('receiver')).toHaveValue('');
    expect(getField('city')).toHaveValue('');
    expect(getDraft().receiver).toBeUndefined();
});

test('blocks submission during parsing and submits the completed parsed fields before resetting', async () => {
    await renderOrder({
        address: originalAddress, country: 'USA', customer_name: 'Existing Customer',
        receiver: 'Existing Receiver', receiver_phone: '555', zip_code: '10001',
    });
    fireEvent.click(screen.getByRole('button', { name: '解析地址' }));
    const submitButton = screen.getByRole('button', { name: '创建/Submit' });
    expect(submitButton).toBeDisabled();
    fireEvent.click(submitButton);
    expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/create'))).toBe(false);
    // A native form submit models Enter, which can bypass a disabled button.
    fireEvent.submit(getField('address').closest('form'));
    await waitFor(() => expect(messageApi.info).toHaveBeenCalledWith('地址正在解析，请稍后创建订单'));
    expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/create'))).toBe(false);
    await finishParsing();
    expect(submitButton).toBeEnabled();

    let resolveOrder;
    const pendingOrder = new Promise((resolve) => { resolveOrder = resolve; });
    const fetchImplementation = global.fetch.getMockImplementation();
    global.fetch.mockImplementation((url, ...args) => (
        url.endsWith('/create') ? pendingOrder : fetchImplementation(url, ...args)
    ));
    fireEvent.click(submitButton);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/create', expect.anything()));
    const [, createRequest] = global.fetch.mock.calls.find(([url]) => url.endsWith('/create'));
    expect(JSON.parse(createRequest.body)).toEqual(expect.objectContaining({
        country: 'USA', province: 'NY', city: 'New York', address: originalAddress,
        zip_code: '10001', receiver: 'Jane Doe', receiver_phone: '+1 212 555 0100', mail: 'jane@example.com',
    }));
    const parseButton = screen.getByRole('button', { name: '解析地址' });
    expect(parseButton).toBeDisabled();
    fireEvent.click(parseButton);
    expect(parseCalls()).toHaveLength(1);
    await act(async () => resolveOrder(response({ code: 200 })));
    await waitFor(() => expect(getField('address')).toHaveValue(''));
    expect(getField('receiver')).toHaveValue('');
    expect(getField('city')).toHaveValue('');
    expect(localStorage.getItem('newOrderFormData')).toBeNull();
});
