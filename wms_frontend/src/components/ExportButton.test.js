import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import ExportButton from './ExportButton';
import { endpoint } from '../config';

jest.mock('antd', () => ({
    Dropdown: {
        Button: ({ children, menu, onClick, loading }) => <>
            <button onClick={onClick} disabled={loading}>{children}</button>
            <select aria-label="导出格式" onChange={event => menu.onClick({ key: event.target.value })}>
                <option value="">选择格式</option>
                {menu.items.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
            </select>
        </>,
    },
    message: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));
jest.mock('@ant-design/icons', () => ({ DownloadOutlined: () => null }));
jest.mock('../common/genWayBill', () => jest.fn());

const templateResponse = () => ({
    json: async () => ({ code: 200, data: [{ mode_key: 'jifei', label: '极飞' }] }),
});
const pdfResponse = () => ({
    ok: true,
    headers: { get: () => 'application/pdf' },
    blob: jest.fn().mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' })),
});

let downloadedFiles;
let originalFetch;
let originalCreateObjectURL;
let originalRevokeObjectURL;

beforeEach(() => {
    jest.clearAllMocks();
    originalFetch = global.fetch;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    global.fetch = jest.fn().mockResolvedValueOnce(templateResponse());
    URL.createObjectURL = jest.fn().mockReturnValue('blob:confirmation-pdf');
    URL.revokeObjectURL = jest.fn();
    downloadedFiles = [];
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
        downloadedFiles.push({ href: this.href, filename: this.download });
    });
    jest.spyOn(console, 'log').mockImplementation(() => {});
    localStorage.setItem('jwt', 'test-token');
});

afterEach(() => {
    jest.restoreAllMocks();
    global.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    localStorage.clear();
});

function chooseConfirmation() {
    fireEvent.change(screen.getByLabelText('导出格式'), { target: { value: 'shippingConfirmation' } });
}

test.each([
    ['all boxes in selected orders', undefined, []],
    ['only selected boxes in an order', ['box-1', 'box-2'], ['box-1', 'box-2']],
])('downloads a PDF for %s and clears the selection after success', async (_name, selectedCargos, expectedCargos) => {
    const response = pdfResponse();
    const onSuccess = jest.fn();
    global.fetch.mockResolvedValueOnce(response);
    render(<ExportButton selectedKeys={['order-1', 'order-2']} selectedCargos={selectedCargos} onSuccess={onSuccess} />);
    await screen.findByRole('option', { name: '极飞' });
    chooseConfirmation();
    fireEvent.click(screen.getByRole('button', { name: '导出出货确认单（PDF）' }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(`${endpoint}/orders/shipping-confirmation/pdf`, {
        method: 'POST',
        headers: expect.objectContaining({ 'x-token': 'test-token', 'Content-Type': 'application/json' }),
        body: JSON.stringify({ uid_list: ['order-1', 'order-2'], cargo_list: expectedCargos }),
    });
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(downloadedFiles).toEqual([{ href: 'blob:confirmation-pdf', filename: expect.stringMatching(/^出货确认单_\d+\.pdf$/) }]);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:confirmation-pdf');
    expect(message.success).toHaveBeenCalledWith('出货确认单导出成功');
});

test.each([
    ['HTTP error', false, 'application/json', { code: 400, msg: '没有可导出的箱子' }],
    ['JSON error with HTTP 200', true, 'application/json', { code: 403, msg: '无权导出此订单' }],
])('shows a %s without downloading JSON or clearing the selection', async (_name, ok, contentType, errorData) => {
    const response = { ok, headers: { get: () => contentType }, json: jest.fn().mockResolvedValue(errorData), blob: jest.fn() };
    const onSuccess = jest.fn();
    global.fetch.mockResolvedValueOnce(response);
    render(<ExportButton selectedKeys={['order-1']} onSuccess={onSuccess} />);
    await screen.findByRole('option', { name: '极飞' });
    chooseConfirmation();
    fireEvent.click(screen.getByRole('button', { name: '导出出货确认单（PDF）' }));

    await waitFor(() => expect(message.error).toHaveBeenCalledWith(errorData.msg));
    expect(response.blob).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(downloadedFiles).toEqual([]);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toBeEnabled();
});

test('shows a useful failure when the server returns a non-JSON error page', async () => {
    global.fetch.mockResolvedValueOnce({
        ok: false,
        headers: { get: () => 'text/html' },
        json: jest.fn().mockRejectedValue(new SyntaxError('Unexpected token')),
    });
    render(<ExportButton selectedKeys={['order-1']} />);
    await screen.findByRole('option', { name: '极飞' });
    chooseConfirmation();
    fireEvent.click(screen.getByRole('button', { name: '导出出货确认单（PDF）' }));

    await waitFor(() => expect(message.error).toHaveBeenCalledWith('出货确认单导出失败'));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toBeEnabled();
});

test.each(['network', 'application'])('keeps fixed PDF export available after a template %s failure', async failureType => {
    global.fetch.mockReset();
    if (failureType === 'network') {
        global.fetch.mockRejectedValueOnce(new Error('offline'));
    } else {
        global.fetch.mockResolvedValueOnce({ json: async () => ({ code: 403, msg: '无权查看 Excel 模板' }) });
    }
    global.fetch.mockResolvedValueOnce(pdfResponse());
    const onSuccess = jest.fn();
    render(<ExportButton selectedKeys={['order-1']} onSuccess={onSuccess} />);
    expect(screen.getByRole('option', { name: '出货确认单（PDF）' })).toBeInTheDocument();
    await waitFor(() => expect(message.error).toHaveBeenCalledWith('获取导出模板失败'));
    chooseConfirmation();
    fireEvent.click(screen.getByRole('button', { name: '导出出货确认单（PDF）' }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(downloadedFiles).toHaveLength(1);
});

test('requires at least one selected order before requesting a PDF', async () => {
    render(<ExportButton selectedKeys={[]} />);
    await screen.findByRole('option', { name: '极飞' });
    chooseConfirmation();
    fireEvent.click(screen.getByRole('button', { name: '导出出货确认单（PDF）' }));

    expect(message.warning).toHaveBeenCalledWith('请先选择要导出的订单');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
});
