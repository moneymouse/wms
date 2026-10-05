import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import OrderHistoryDrawer from './OrderHistoryDrawer';

const version = {
    id: 2,
    order_uid: 'order-1',
    version_no: 2,
    action: 'box_updated',
    summary: '修改箱子内容',
    operator_name: '店长甲',
    operator_roles: ['store_manager'],
    created_at: '2026-09-16 10:00:00',
    change_summary: [{
        sequence_no: 1,
        entity_type: 'box',
        entity_uid: 'box-1',
        operation: 'update',
        fields: ['item_details', 'transfer_id'],
    }],
};

const detail = {
    ...version,
    changes: [{
        sequence_no: 1,
        entity_type: 'box',
        entity_uid: 'box-1',
        operation: 'update',
        fields: ['item_details', 'transfer_id'],
        before_data: {
            transfer_id: 'OLD-1',
            item_details: [{ item_name: '旧品名', customs_code: '1001', piece_count: 1 }],
        },
        after_data: {
            transfer_id: 'NEW-1',
            item_details: [{ item_name: '新品名', customs_code: '1002', piece_count: 2 }],
        },
    }],
    snapshot: {
        deleted: false,
        order: { uid: 'order-1', order_id: 'ORDER-1', customer_name: '客户甲' },
        cargos: [],
        boxes: [{
            uid: 'box-1',
            transfer_id: 'NEW-1',
            waybill_id: 'WB-1',
            item_details: [{ item_name: '新品名', customs_code: '1002', piece_count: 2 }],
            weight: 3.2,
        }],
    },
};

beforeEach(() => {
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
        if (url.includes('/versions/2')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ code: 200, data: detail }) });
        }
        if (url.includes('/orders/order-1/versions')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ code: 200, data: { items: [version], total: 1, page: 1, page_size: 10 } }),
            });
        }
        if (url.includes('/order-history')) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    code: 200,
                    data: { items: [{ ...version, deleted: true, order_id: 'ORDER-1', customer_name: '客户甲' }], total: 1, page: 1, page_size: 10 },
                }),
            });
        }
        return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
});

afterEach(() => {
    jest.restoreAllMocks();
});

test('renders paged versions, full before/after item tables and reconstructed snapshot', async () => {
    render(<OrderHistoryDrawer open onClose={jest.fn()} orderUid="order-1" orderId="ORDER-1" />);

    expect(await screen.findByText('修改箱子内容')).toBeInTheDocument();
    expect(screen.getByText(/店长甲.*店长/)).toBeInTheDocument();
    const versionRegion = screen.getByRole('region', { name: '版本记录' });
    const initialDetailRegion = screen.getByRole('region', { name: '版本详情' });
    expect(versionRegion.parentElement).toBe(initialDetailRegion.parentElement);
    expect(within(initialDetailRegion).getByText('请从左侧选择要查看的差异或完整版本')).toBeInTheDocument();

    fireEvent.click(within(versionRegion).getByRole('button', { name: '查看差异' }));
    const changesRegion = await screen.findByRole('region', { name: 'V2 本次差异' });
    await waitFor(() => expect(changesRegion).toHaveFocus());
    expect(await screen.findByText('旧品名')).toBeInTheDocument();
    expect(screen.getByText('新品名')).toBeInTheDocument();
    expect(screen.getByText('OLD-1')).toBeInTheDocument();
    expect(screen.getByText('NEW-1')).toBeInTheDocument();

    fireEvent.click(within(versionRegion).getByRole('button', { name: '查看该版本' }));
    const snapshotRegion = await screen.findByRole('region', { name: 'V2 完整快照' });
    await waitFor(() => expect(snapshotRegion).toHaveFocus());
    expect(await screen.findByText('V2 完整快照')).toBeInTheDocument();
    expect(screen.getByText('客户甲')).toBeInTheDocument();
    expect(screen.getAllByText('转单号（运单号）').length).toBeGreaterThan(0);
});

test('deleted mode searches tombstones and reuses the version view', async () => {
    render(<OrderHistoryDrawer open onClose={jest.fn()} deletedMode />);

    expect(await screen.findByText('ORDER-1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /查看/ }));

    expect(await screen.findByText('返回已删除订单列表')).toBeInTheDocument();
    expect(await screen.findByText('修改箱子内容')).toBeInTheDocument();
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/orders/order-1/versions'))).toBe(true));
});
