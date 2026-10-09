import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { message, Upload } from 'antd';
import UploadOrder from './uploadOrder';

jest.mock('../pages/supplierReconciliation', () => function Reconciliation() { return <div>统一对账上传工作台</div>; });
jest.mock('antd', () => {
    const actual = jest.requireActual('antd');
    return {
        ...actual,
        message: { ...actual.message, success: jest.fn(), warning: jest.fn(), error: jest.fn() },
        Upload: {
            ...actual.Upload,
            Dragger: jest.fn(({ children }) => <div>{children}</div>),
        },
    };
});

beforeEach(() => {
    jest.clearAllMocks();
    URL.createObjectURL = jest.fn(() => `blob:upload-report-${URL.createObjectURL.mock.calls.length}`);
    URL.revokeObjectURL = jest.fn();
    window.localStorage.clear();
    window.matchMedia = jest.fn(query => ({ matches: false, media: query, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn() }));
});
function login(payload) { localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify(payload))}.signature`); }

test.each(['admin', 'clerk'])('%s can open reconciliation without changing the transfer-number upload', role => {
    login({ roles: [role] });
    render(<UploadOrder />);
    expect(screen.getByRole('tab', { name: '原单号-转单号表' })).toBeInTheDocument();
    expect(screen.getByText('transfer_id')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '上传对账明细' }));
    expect(screen.getByText('统一对账上传工作台')).toBeVisible();
});

test.each(['salesperson', 'store_manager'])('%s retains the existing upload without seeing third-party costs', role => {
    login({ roles: [role] });
    render(<UploadOrder />);
    expect(screen.getByRole('tab', { name: '原单号-转单号表' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '上传对账明细' })).not.toBeInTheDocument();
});

test('legacy clerk role is honored when roles contains another role', () => {
    login({ role: 'clerk', roles: ['salesperson'] });
    render(<UploadOrder />);
    expect(screen.getByRole('tab', { name: '上传对账明细' })).toBeInTheDocument();
});

function uploadProps() { return Upload.Dragger.mock.calls.slice(-1)[0][0]; }

test('partial results use warning and each finished upload creates only one report', () => {
    login({ roles: ['clerk'] });
    render(<UploadOrder />);
    const file = { uid: 'file-1', name: '转单表.xlsx', status: 'done', response: {
        code: 207, msg: '部分订单上传失败，其他订单已保存',
        success_items: [{ uid: 'cargo-1', transfer_id: 'ORIGINAL-1', waybill_id: 'WB-SHARED' }],
        failed_list: [{ order_id: 'ORDER-2', transfer_id: 'ORIGINAL-2', waybill_id: 'WB-SHARED', reason: '客户归属不一致' }],
    } };
    act(() => uploadProps().onChange({ file, fileList: [file] }));
    expect(message.warning).toHaveBeenCalledTimes(1);
    expect(message.error).not.toHaveBeenCalled();
    expect(uploadProps().fileList).toHaveLength(1);
    expect(uploadProps().fileList[0]).toMatchObject({
        uid: 'file-1', status: 'error', url: 'blob:upload-report-1',
        linkProps: { download: '转单表.xlsx上传结果记录.txt' },
    });
    act(() => uploadProps().onChange({ file, fileList: [file] }));
    expect(message.warning).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(uploadProps().fileList).toHaveLength(1);

    const secondFile = { uid: 'file-2', name: '补充表.xlsx', status: 'done', response: {
        code: 200, success_items: [{ uid: 'cargo-2' }], failed_list: [],
    } };
    act(() => uploadProps().onChange({ file: secondFile, fileList: [file, secondFile] }));
    expect(uploadProps().fileList).toHaveLength(2);
    expect(message.success).toHaveBeenCalledTimes(1);
    expect(message.warning).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    act(() => uploadProps().onChange({ file: { ...file, status: 'removed' }, fileList: [secondFile] }));
    expect(uploadProps().fileList).toHaveLength(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:upload-report-1');
});

test('an HTTP error containing saved results shows the tracking warning instead of upload failure', () => {
    login({ roles: ['clerk'] });
    render(<UploadOrder />);
    const file = { uid: 'file-1', name: '转单表.xlsx', status: 'error', xhr: { status: 502, response: JSON.stringify({
        code: 502, msg: '17track rejected', success_items: [{ uid: 'cargo-1' }], failed_list: [],
        tracking_error: { code: 502, reason: '追踪服务拒绝' }, rejected: [{ number: 'WB-1' }],
    }) } };
    act(() => uploadProps().onChange({ file, fileList: [file] }));
    expect(message.warning).toHaveBeenCalledWith(expect.stringContaining('已保存 1 条，追踪注册失败'));
    expect(message.error).not.toHaveBeenCalled();
});

test('a successful repeated submission stays successful', () => {
    login({ roles: ['clerk'] });
    render(<UploadOrder />);
    const file = { uid: 'file-1', name: '转单表.xlsx', status: 'done', response: {
        code: 200, cargo_count: 1, success_items: [{ uid: 'cargo-1' }], failed_list: [],
    } };
    act(() => uploadProps().onChange({ file, fileList: [file] }));
    expect(uploadProps().fileList[0].status).toBe('done');
    expect(message.success).toHaveBeenCalledWith('转单表.xlsx：已保存 1 条');
    expect(message.error).not.toHaveBeenCalled();
    expect(message.warning).not.toHaveBeenCalled();
});
