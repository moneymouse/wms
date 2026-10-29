import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import OrderList from './orderList';
import PackingListList from './packingListList';

jest.mock('../components/ExportButton', () => () => null);
jest.mock('../components/FeatureTour', () => () => null);
jest.mock('../components/OrderHistoryDrawer', () => () => null);
jest.mock('../components/MyPackingLists', () => () => null);

function Navigation({ destination }) {
    const location = useLocation();
    const navigate = useNavigate();
    return <>
        <output data-testid="current-url">{location.pathname}{location.search}{location.hash}</output>
        <button onClick={() => navigate(destination)}>恢复另一个筛选链接</button>
        <button onClick={() => navigate(-1)}>返回上一组筛选</button>
    </>;
}
const currentQuery = () => new URL(screen.getByTestId('current-url').textContent, 'http://localhost').searchParams;
const lastRequest = () => new URL(global.fetch.mock.calls[global.fetch.mock.calls.length - 1][0], 'http://localhost');

beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear();
    window.localStorage.setItem('jwt', `h.${window.btoa(JSON.stringify({ user_id: 7, roles: ['salesperson'] }))}.s`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: false, media: query, onchange: null, addListener() {}, removeListener() {},
        addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false,
    }) });
    global.fetch = jest.fn(async rawUrl => ({ ok: true, json: async () => ({ code: 200,
        data: String(rawUrl).includes('/packing-lists') ? { items: [], total: 100 } : [], total: 100,
    }) }));
});
afterEach(() => jest.restoreAllMocks());

test('orders restore query, page and sorting from links and back navigation; editing preserves unrelated parameters', async () => {
    render(<MemoryRouter initialEntries={['/orders?q=first&p=2&sf=order_date&so=0&keep=yes#anchor']}>
        <Navigation destination="/orders?q=second&p=3&sf=update_date&so=1&keep=yes#anchor" /><OrderList />
    </MemoryRouter>);
    const input = screen.getByPlaceholderText('订单号/客户名/收件人名/业务员/国家');
    expect(input).toHaveValue('first');
    await waitFor(() => expect(lastRequest().searchParams.get('p')).toBe('2'));
    expect(lastRequest().searchParams.get('sf')).toBe('order_date');
    expect(lastRequest().searchParams.get('so')).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: '恢复另一个筛选链接' }));
    await waitFor(() => expect(input).toHaveValue('second'));
    expect(lastRequest().searchParams.get('p')).toBe('3');
    expect(lastRequest().searchParams.get('sf')).toBe('update_date');
    fireEvent.click(screen.getByRole('button', { name: '返回上一组筛选' }));
    await waitFor(() => expect(input).toHaveValue('first'));
    expect(lastRequest().searchParams.get('p')).toBe('2');
    fireEvent.change(input, { target: { value: 'third' } });
    await waitFor(() => expect(currentQuery().get('q')).toBe('third'));
    expect(currentQuery().get('p') || '1').toBe('1');
    expect(currentQuery().get('keep')).toBe('yes');
    expect(screen.getByTestId('current-url').textContent).toContain('#anchor');
    await waitFor(() => expect(lastRequest().searchParams.get('q')).toBe('third'));
});

test('packing-list restores the input, status and page without a debounced old input overwriting the URL', async () => {
    render(<MemoryRouter initialEntries={['/packing-lists?search=old&page=3&status=已出库&excludeStatus=false&keep=yes']}>
        <Navigation destination="/packing-lists?search=new&page=2&status=草稿&excludeStatus=true&keep=yes" /><PackingListList />
    </MemoryRouter>);
    const input = screen.getByPlaceholderText('搜索唛头或客户名');
    expect(input).toHaveValue('old');
    expect(screen.getByRole('checkbox', { name: '排除所选状态' })).not.toBeChecked();
    await waitFor(() => expect(lastRequest().searchParams.get('p')).toBe('3'));
    expect(lastRequest().searchParams.get('box_status')).toBe('outbound');
    fireEvent.click(screen.getByRole('button', { name: '恢复另一个筛选链接' }));
    await waitFor(() => expect(input).toHaveValue('new'));
    expect(screen.getByRole('checkbox', { name: '排除所选状态' })).toBeChecked();
    await waitFor(() => expect(lastRequest().searchParams.get('box_status')).toBe('draft'));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 600)); });
    expect(currentQuery().get('search')).toBe('new');
    expect(currentQuery().get('page')).toBe('2');
    fireEvent.click(screen.getByRole('checkbox', { name: '排除所选状态' }));
    await waitFor(() => expect(currentQuery().get('excludeStatus')).toBe('false'));
    expect(currentQuery().get('page') || '1').toBe('1');
    expect(currentQuery().get('search')).toBe('new');
    expect(currentQuery().get('keep')).toBe('yes');
});

test('an explicit empty packing status filter survives a link instead of restoring the default exclusion', async () => {
    render(<MemoryRouter initialEntries={['/packing-lists?status=&excludeStatus=false&search=all']}><PackingListList /></MemoryRouter>);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(lastRequest().searchParams.get('q')).toBe('all');
    expect(lastRequest().searchParams.has('box_status')).toBe(false);
    expect(screen.getByRole('checkbox', { name: '排除所选状态' })).not.toBeChecked();
});
