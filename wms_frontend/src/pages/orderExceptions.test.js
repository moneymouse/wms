import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import OrderExceptions from './orderExceptions';
import { addExceptionFollowup, fetchExceptionSalespeople, fetchOrderException, fetchOrderExceptions, resolveOrderException } from '../common/orderExceptionApi';

jest.mock('../common/orderExceptionApi', () => ({
    ...jest.requireActual('../common/orderExceptionApi'),
    addExceptionFollowup: jest.fn(), fetchExceptionSalespeople: jest.fn(), fetchOrderException: jest.fn(), fetchOrderExceptions: jest.fn(), resolveOrderException: jest.fn(),
}));
jest.mock('../components/OrderExceptionRegistration', () => ({
    ...jest.requireActual('../components/OrderExceptionRegistration'),
    __esModule: true, default: ({ open }) => open ? <span>登记异常表单</span> : null,
}));
const record = { uid: 'exception-1', order_uid: 'order-1', order_id: 'ORDER-1', cargo_uid: 'cargo-1', origin_id: 'ORIGIN-1', waybill_id: 'WAY-1',
    salesman_id: 7, salesman_name: '业务员甲', reason: '包装破损', source: 'manual', status: 'open', created_at: '2026-10-11 12:00:00',
    can_followup: true, can_resolve: true, history: [{ uid: 'h-1', action: 'registered', note: '包装破损', actor_name: '文员甲', created_at: '2026-10-11 12:00:00' }] };
function Harness() {
    const location = useLocation(); const navigate = useNavigate();
    return <><OrderExceptions /><output data-testid="location">{location.pathname}{location.search}{location.hash}</output>
        <button onClick={() => navigate('/order-exceptions?exception_uid=exception-2')}>打开另一个异常</button></>;
}
function showPage(entry = '/order-exceptions') { return render(<MemoryRouter initialEntries={[entry]}><Harness /></MemoryRouter>); }
function setRoles(roles) { localStorage.setItem('jwt', `h.${btoa(JSON.stringify({ user_id: 7, roles }))}.s`); }
beforeEach(() => {
    jest.clearAllMocks(); localStorage.clear(); setRoles(['salesperson']);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: false, media: query,
        onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {} }) });
    fetchOrderExceptions.mockResolvedValue({ items: [record], total: 1 });
    fetchOrderException.mockResolvedValue(record);
    fetchExceptionSalespeople.mockResolvedValue([{ id: 7, name: '业务员甲' }, { id: 8, name: '业务员乙' }]);
    addExceptionFollowup.mockResolvedValue({ ...record, history: [...record.history, { uid: 'h-2', action: 'followup', note: '已联系客户', actor_name: '业务员甲', created_at: '2026-10-11 13:00:00' }] });
    resolveOrderException.mockResolvedValue({ ...record, status: 'resolved', can_followup: false, can_resolve: false, resolved_at: '2026-10-11 14:00:00',
        history: [...record.history, { uid: 'h-3', action: 'resolved', note: '手动标记已解决', actor_name: '业务员甲', created_at: '2026-10-11 14:00:00' }] });
});
afterEach(() => jest.restoreAllMocks());

test('salesperson defaults to own open cases and can select a status without requesting another owner', async () => {
    showPage(); await screen.findByRole('button', { name: '查看跟进' });
    expect(fetchOrderExceptions.mock.calls[0][0]).toMatchObject({ page: 1, status: 'open' });
    expect(fetchOrderExceptions.mock.calls[0][0]).not.toHaveProperty('salesmanId');
    expect(fetchExceptionSalespeople).not.toHaveBeenCalled();
    expect(screen.queryByRole('combobox', { name: '查看业务员' })).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '异常状态' }));
    fireEvent.click(await screen.findByText('已解决', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(fetchOrderExceptions).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'resolved', page: 1 })));
});

test('admin defaults to current business identity and can switch to another salesperson', async () => {
    setRoles(['admin']); showPage();
    await screen.findByRole('button', { name: '查看跟进' });
    expect(fetchOrderExceptions.mock.calls[0][0]).toMatchObject({ salesmanId: 7 });
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '查看业务员' }));
    fireEvent.click(await screen.findByText('业务员乙', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(fetchOrderExceptions).toHaveBeenLastCalledWith(expect.objectContaining({ salesmanId: 8, page: 1 })));
});

test('clerk can register but never fetches exception lists or linked private history', async () => {
    setRoles(['clerk']); showPage('/order-exceptions?exception_uid=private-case');
    fireEvent.click(screen.getByRole('button', { name: '登记异常' }));
    expect(screen.getByText('登记异常表单')).toBeInTheDocument();
    expect(fetchOrderExceptions).not.toHaveBeenCalled(); expect(fetchOrderException).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('deep link loads exact case and shows linked order/package/history, while close preserves other query and hash', async () => {
    showPage('/order-exceptions?exception_uid=outside-page&view=returned#record');
    const drawer = await screen.findByRole('dialog', { name: '异常跟进 · ORDER-1' });
    expect(fetchOrderException).toHaveBeenCalledWith('outside-page', expect.anything());
    expect(within(drawer).getByRole('link', { name: 'ORDER-1' })).toHaveAttribute('href', '/orders/order-1');
    expect(within(drawer).getByText('ORIGIN-1 / WAY-1')).toBeInTheDocument();
    expect(within(drawer).getByText('文员甲 · 2026-10-11 12:00:00')).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/order-exceptions?view=returned#record'));
    expect(addExceptionFollowup).not.toHaveBeenCalled(); expect(resolveOrderException).not.toHaveBeenCalled();
});

test('failed followup retains notes and event key, then appends returned history on retry', async () => {
    addExceptionFollowup.mockRejectedValueOnce(new Error('保存失败，请重试'));
    showPage('/order-exceptions?exception_uid=exception-1');
    const drawer = await screen.findByRole('dialog', { name: '异常跟进 · ORDER-1' });
    fireEvent.change(within(drawer).getByLabelText('跟进内容'), { target: { value: '已联系客户' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '保存跟进' }));
    await within(drawer).findByText('保存失败，请重试');
    await waitFor(() => expect(within(drawer).getByRole('button', { name: '保存跟进' })).not.toHaveClass('ant-btn-loading'));
    expect(within(drawer).getByLabelText('跟进内容')).toHaveValue('已联系客户');
    fireEvent.click(within(drawer).getByRole('button', { name: '保存跟进' }));
    await within(drawer).findByText('业务跟进');
    expect(addExceptionFollowup.mock.calls[1]).toEqual(addExceptionFollowup.mock.calls[0]);
    expect(within(drawer).getByLabelText('跟进内容')).toHaveValue('');
    expect(resolveOrderException).not.toHaveBeenCalled();
});

test('resolution requires an explicit user action and removes mutation controls after success', async () => {
    showPage('/order-exceptions?exception_uid=exception-1');
    const drawer = await screen.findByRole('dialog', { name: '异常跟进 · ORDER-1' });
    expect(resolveOrderException).not.toHaveBeenCalled();
    fireEvent.click(within(drawer).getByRole('button', { name: '标记已解决' }));
    // Ant Design uses the same title ID for simultaneous dialogs in test mode.
    const modal = await waitFor(() => {
        const dialog = screen.getAllByRole('dialog').find(element => element.classList.contains('ant-modal'));
        expect(dialog).toBeInTheDocument(); return dialog;
    });
    expect(resolveOrderException).not.toHaveBeenCalled();
    fireEvent.click(within(modal).getByRole('button', { name: '确认已解决' }));
    await within(drawer).findByText('手动标记已解决');
    expect(resolveOrderException).toHaveBeenCalledWith('exception-1', { event_key: expect.any(String) });
    expect(within(drawer).queryByRole('button', { name: '保存跟进' })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', { name: '标记已解决' })).not.toBeInTheDocument();
});

test('admin viewing someone else honors backend read-only flags', async () => {
    setRoles(['admin']); fetchOrderException.mockResolvedValue({ ...record, salesman_id: 8, can_followup: false, can_resolve: false });
    showPage('/order-exceptions?exception_uid=exception-1');
    const drawer = await screen.findByRole('dialog', { name: '异常跟进 · ORDER-1' });
    expect(within(drawer).getByText('仅对应业务员可跟进和标记已解决，当前记录为只读。')).toBeInTheDocument();
    expect(within(drawer).queryByLabelText('跟进内容')).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', { name: '标记已解决' })).not.toBeInTheDocument();
});

test('forbidden deep links show server denial without broadening owner scope', async () => {
    fetchOrderException.mockRejectedValue(new Error('无权查看该异常'));
    showPage('/order-exceptions?exception_uid=someone-elses');
    await screen.findByText('无权查看该异常');
    expect(screen.queryByLabelText('跟进内容')).not.toBeInTheDocument();
    expect(fetchOrderExceptions).toHaveBeenCalledTimes(1);
    expect(fetchOrderExceptions.mock.calls[0][0]).not.toHaveProperty('salesmanId');
});

test('a later linked case aborts the old load and ignores its eventual response', async () => {
    let resolveFirst;
    fetchOrderException.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
        .mockResolvedValueOnce({ ...record, uid: 'exception-2', order_id: 'ORDER-2' });
    showPage('/order-exceptions?exception_uid=exception-1');
    await waitFor(() => expect(fetchOrderException).toHaveBeenCalledTimes(1));
    const signal = fetchOrderException.mock.calls[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: '打开另一个异常' }));
    await screen.findByRole('dialog', { name: '异常跟进 · ORDER-2' });
    expect(signal.aborted).toBe(true);
    await act(async () => resolveFirst(record));
    expect(screen.queryByRole('dialog', { name: '异常跟进 · ORDER-1' })).not.toBeInTheDocument();
});

test('URL restores exception filters and changing status preserves the owner, detail link and hash', async () => {
    setRoles(['admin']);
    showPage('/order-exceptions?exception_status=resolved&exception_salesman=8&exception_page=3&exception_uid=exception-1&source=message#history');
    await screen.findByRole('dialog', { name: '异常跟进 · ORDER-1' });
    expect(fetchOrderExceptions).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'resolved', salesmanId: 8, page: 3 }));
    expect(screen.getByLabelText('异常状态', { selector: 'input' }).closest('.ant-select')).toHaveTextContent('已解决');
    expect(screen.getByLabelText('查看业务员', { selector: 'input' }).closest('.ant-select')).toHaveTextContent('业务员乙');
    fireEvent.mouseDown(screen.getByLabelText('异常状态', { selector: 'input' }));
    fireEvent.click(await screen.findByText('全部', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(fetchOrderExceptions).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'all', salesmanId: 8, page: 1 })));
    await waitFor(() => expect(new URL(screen.getByTestId('location').textContent, 'http://localhost').searchParams.get('exception_status')).toBe('all'));
    const url = new URL(screen.getByTestId('location').textContent, 'http://localhost');
    expect(url.searchParams.get('exception_status')).toBe('all');
    expect(url.searchParams.get('exception_salesman')).toBe('8');
    expect(url.searchParams.get('exception_uid')).toBe('exception-1');
    expect(url.searchParams.get('source')).toBe('message');
    expect(url.hash).toBe('#history');
    expect(fetchOrderException).toHaveBeenCalledTimes(1);
});
