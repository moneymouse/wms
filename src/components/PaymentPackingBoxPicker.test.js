import React, { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import PaymentPackingBoxPicker from './PaymentPackingBoxPicker';

const response = data => Promise.resolve({ ok: true, status: 200, json: async () => ({ code: 200, data }) });
const box = { box_uid: 'box-1', list_number: 'MARK-A', packing_list_uid: 'packing-a', box_number: 1, transfer_id: 'XD123456L', weight: 5, item_name: '服装', customer_id: 2, target_order_uid: null };
const secondBox = { ...box, box_uid: 'box-2', box_number: 2, transfer_id: 'XD654321L' };
const otherBox = { ...box, box_uid: 'box-b', list_number: 'MARK-B', packing_list_uid: 'packing-b', transfer_id: 'XD999999L' };
function Picker({ customerId = 2, onChange = jest.fn(), disabled = false }) {
    const [value, setValue] = useState([]);
    return <PaymentPackingBoxPicker customerId={customerId} disabled={disabled} value={value} onChange={next => { setValue(next); onChange(next); }} />;
}
const openList = async listNumber => {
    fireEvent.click(await screen.findByRole('button', { name: `展开装箱单 ${listNumber}` }));
    return screen.getByRole('group', { name: `装箱单 ${listNumber} 的箱子` });
};
const submitSearch = query => {
    const search = screen.getByRole('searchbox', { name: '搜索备注装箱单箱子' });
    fireEvent.change(search, { target: { value: query } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
    fireEvent.keyUp(search, { key: 'Enter', code: 'Enter', keyCode: 13 });
};
const tickBox = (group, name) => fireEvent.click(within(group).getByRole('checkbox', { name: `选择备注箱子 ${name}` }));

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
    global.fetch = jest.fn(() => response({ items: [box, secondBox, otherBox], total: 3, page_size: 200 }));
});
afterEach(() => jest.restoreAllMocks());

test('one parent per packing list expands exact boxes and preserves other list selections', async () => {
    const onChange = jest.fn(); render(<Picker onChange={onChange} />);
    await screen.findByText('MARK-A');
    expect(screen.getByText('共 2 张装箱单')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByText('XD123456L')).not.toBeInTheDocument();
    const groupA = await openList('MARK-A');
    expect(within(groupA).getAllByText('待分配')).toHaveLength(2);
    tickBox(groupA, 'MARK-A / 箱 1');
    fireEvent.click(screen.getByRole('button', { name: '收起装箱单 MARK-A' }));
    const groupB = await openList('MARK-B');
    tickBox(groupB, 'MARK-B / 箱 1');
    expect(onChange).toHaveBeenLastCalledWith(['box-1', 'box-b']);
    const reopened = await openList('MARK-A');
    expect(within(reopened).getByRole('checkbox', { name: '选择备注箱子 MARK-A / 箱 1' })).toBeChecked();
    tickBox(reopened, 'MARK-A / 箱 2');
    expect(onChange).toHaveBeenLastCalledWith(['box-b', 'box-1', 'box-2']);
    fireEvent.click(within(groupB).getAllByRole('checkbox')[0]);
    expect(onChange).toHaveBeenLastCalledWith(['box-1', 'box-2']);
    fireEvent.click(screen.getByRole('button', { name: '移除备注箱子 MARK-A / 箱 1' }));
    expect(onChange).toHaveBeenLastCalledWith(['box-2']);
});

test('box API pages are fully grouped before paginating packing-list parents', async () => {
    const rows = Array.from({ length: 201 }, (_, index) => ({ ...box, box_uid: `box-a-${index + 1}`, box_number: index + 1 }));
    rows.push(...Array.from({ length: 10 }, (_, index) => ({ ...otherBox, box_uid: `box-b-${index + 1}`, packing_list_uid: `packing-b-${index + 1}`, list_number: `MARK-B-${index + 1}` })));
    global.fetch.mockImplementation(url => {
        const params = new URL(url, 'http://localhost').searchParams;
        const page = Number(params.get('p'));
        return response({ items: rows.slice((page - 1) * 200, page * 200), total: rows.length, page_size: 200 });
    });
    const onChange = jest.fn(); render(<Picker onChange={onChange} />);
    await screen.findByText('201 箱');
    expect(screen.getAllByRole('button', { name: '展开装箱单 MARK-A' })).toHaveLength(1);
    expect(screen.getByText('共 11 张装箱单')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);
    const firstGroup = await openList('MARK-B-1'); tickBox(firstGroup, 'MARK-B-1 / 箱 1');
    fireEvent.click(screen.getByTitle('2'));
    const lastGroup = await openList('MARK-B-10'); tickBox(lastGroup, 'MARK-B-10 / 箱 1');
    expect(onChange).toHaveBeenLastCalledWith(['box-b-1', 'box-b-10']);
    fireEvent.click(screen.getByTitle('1'));
    const retained = screen.getByRole('group', { name: '装箱单 MARK-B-1 的箱子' });
    expect(within(retained).getByRole('checkbox', { name: '选择备注箱子 MARK-B-1 / 箱 1' })).toBeChecked();
    expect(global.fetch).toHaveBeenCalledTimes(2);
});

test('search matches a parent but expansion loads all its boxes without the search filter', async () => {
    global.fetch.mockImplementation(url => {
        const params = new URL(url, 'http://localhost').searchParams;
        return response({ items: params.get('q') ? [box] : [box, secondBox], total: params.get('q') ? 1 : 2, page_size: 200 });
    });
    const onChange = jest.fn(); render(<Picker onChange={onChange} />);
    const initial = await openList('MARK-A'); tickBox(initial, 'MARK-A / 箱 1');
    submitSearch('XD123456L');
    await screen.findByText('匹配 1 箱');
    const group = await openList('MARK-A');
    await within(group).findByText('XD654321L');
    tickBox(group, 'MARK-A / 箱 2');
    expect(onChange).toHaveBeenLastCalledWith(['box-1', 'box-2']);
    const fullLookup = global.fetch.mock.calls.map(([url]) => new URL(url, 'http://localhost')).find(url => url.searchParams.get('packing_list_uid') === 'packing-a');
    expect(fullLookup.searchParams.has('q')).toBe(false);
    expect(screen.getAllByText('2 箱')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: '收起装箱单 MARK-A' }));
    await openList('MARK-A');
    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes('packing_list_uid'))).toHaveLength(1);
});

test('switching customers clears old box references and keeps lookup scoped', async () => {
    const onChange = jest.fn(); const { rerender } = render(<Picker onChange={onChange} />);
    tickBox(await openList('MARK-A'), 'MARK-A / 箱 1');
    rerender(<Picker customerId={3} onChange={onChange} />);
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([]));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => String(url).includes('customer_id=3'))).toBe(true));
    await screen.findByRole('button', { name: '展开装箱单 MARK-A' });
    expect(screen.queryByRole('button', { name: '移除备注箱子 MARK-A / 箱 1' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '收起装箱单 MARK-A' })).not.toBeInTheDocument();
});

test('search ignores a stale response after a newer search', async () => {
    let resolveOld;
    global.fetch.mockImplementation(url => String(url).includes('q=old') ? new Promise(resolve => { resolveOld = resolve; })
        : response({ items: [{ ...box, list_number: String(url).includes('q=new') ? 'NEW-MARK' : 'MARK-A' }], total: 1 }));
    render(<Picker />); await screen.findByText('MARK-A');
    submitSearch('old'); submitSearch('new');
    await screen.findByText('NEW-MARK');
    await act(async () => resolveOld(await response({ items: [{ ...box, list_number: 'OLD-MARK' }], total: 1 })));
    expect(screen.queryByText('OLD-MARK')).not.toBeInTheDocument();
});

test('a stale expanded-child response cannot leak after changing customer', async () => {
    let resolveChild;
    global.fetch.mockImplementation(url => {
        const params = new URL(url, 'http://localhost').searchParams;
        if (params.get('packing_list_uid')) return new Promise(resolve => { resolveChild = resolve; });
        return response({ items: params.get('customer_id') === '3' ? [otherBox] : [box], total: 1 });
    });
    const { rerender } = render(<Picker />); await screen.findByText('MARK-A'); submitSearch('XD123456L');
    await screen.findByText('匹配 1 箱'); await openList('MARK-A');
    await waitFor(() => expect(resolveChild).toBeDefined());
    rerender(<Picker customerId={3} />); await screen.findByText('MARK-B');
    await act(async () => resolveChild(await response({ items: [secondBox], total: 1 })));
    expect(screen.queryByText('XD654321L')).not.toBeInTheDocument();
    expect(screen.queryByText('MARK-A')).not.toBeInTheDocument();
});

test('a failed aggregate page shows an error without exposing incomplete parents and can retry', async () => {
    const rows = Array.from({ length: 201 }, (_, index) => ({ ...box, box_uid: `box-${index}`, box_number: index }));
    let fail = true;
    global.fetch.mockImplementation(url => {
        const page = Number(new URL(url, 'http://localhost').searchParams.get('p'));
        if (page === 2 && fail) return Promise.reject(new Error('后续箱子页加载失败'));
        return response({ items: rows.slice((page - 1) * 200, page * 200), total: rows.length, page_size: 200 });
    });
    render(<Picker />);
    await screen.findByText('后续箱子页加载失败');
    expect(screen.queryByRole('button', { name: '展开装箱单 MARK-A' })).not.toBeInTheDocument();
    fail = false; fireEvent.click(screen.getByRole('button', { name: '重试装箱单加载' }));
    await screen.findByText('201 箱');
});

test('expanded child lookup errors preserve saved choices and retry the complete list', async () => {
    let fail = true;
    global.fetch.mockImplementation(url => {
        const params = new URL(url, 'http://localhost').searchParams;
        if (params.get('packing_list_uid') && fail) return Promise.reject(new Error('装箱单箱子加载失败'));
        return response({ items: params.get('packing_list_uid') ? [box, secondBox] : [box], total: params.get('packing_list_uid') ? 2 : 1 });
    });
    const onChange = jest.fn(); render(<Picker onChange={onChange} />);
    tickBox(await openList('MARK-A'), 'MARK-A / 箱 1'); submitSearch('服装');
    await screen.findByText('匹配 1 箱'); const group = await openList('MARK-A');
    await within(group).findByText('装箱单箱子加载失败');
    expect(screen.getByText('已选 1 箱')).toBeInTheDocument();
    fail = false; fireEvent.click(within(group).getByRole('button', { name: '重试箱子加载' }));
    await within(group).findByText('XD654321L'); tickBox(group, 'MARK-A / 箱 2');
    expect(onChange).toHaveBeenLastCalledWith(['box-1', 'box-2']);
});

test('saved snapshot labels remain available when disabled and no lookup runs', () => {
    render(<PaymentPackingBoxPicker customerId={2} value={['box-1']} selectedBoxes={[box]} disabled />);
    expect(screen.getByRole('button', { name: '移除备注箱子 MARK-A / 箱 1' })).toBeDisabled();
    expect(screen.getByRole('searchbox', { name: '搜索备注装箱单箱子' })).toBeDisabled();
    expect(global.fetch).not.toHaveBeenCalled();
});

test('unbound packing lists can be selected before an order exists', async () => {
    global.fetch.mockImplementation(() => response({ items: [{ ...box, customer_id: null }], total: 1 }));
    const onChange = jest.fn(); render(<Picker onChange={onChange} />);
    await screen.findByText('未绑定客户');
    tickBox(await openList('MARK-A'), 'MARK-A / 箱 1');
    expect(onChange).toHaveBeenLastCalledWith(['box-1']);
});
