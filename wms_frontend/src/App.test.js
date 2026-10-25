import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import App from './App';
import { FEATURE_TOUR_FLOW_EVENT, shouldAutoShowFeatureTour } from './common/featureTourState';

jest.mock('./components/MessageInbox', () => () => null);

jest.mock('./common/featureTourState', () => ({ ...jest.requireActual('./common/featureTourState'), shouldAutoShowFeatureTour: jest.fn(() => true) }));
function setJwt(userId, roles, name = 'Test User') { window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: userId, name, roles }))}.signature`); }
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear(); shouldAutoShowFeatureTour.mockClear();
    setViewport(1280);
});

test.each(['admin', 'salesperson', 'finance'])('%s can navigate to the unified payments page', async role => {
    setJwt(1, [role]); render(<MemoryRouter initialEntries={['/receipts']}><App /></MemoryRouter>);
    expect(await screen.findByText('收付款')).toBeInTheDocument();
    expect(screen.queryByText('收款管理')).not.toBeInTheDocument();
});

test('multi-role labels use spacing without punctuation separators', async () => {
    setJwt(11, ['admin', 'salesperson'], 'Multi Role Test'); render(<MemoryRouter><App /></MemoryRouter>);
    await screen.findByText('Multi Role Test');
    expect(await screen.findByText('管理员')).toHaveStyle({ whiteSpace: 'nowrap' }); expect(screen.getByText('业务员')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.queryByText('，')).not.toBeInTheDocument();
});

test('entering payments clears the retired order-selection receipt workflow', async () => {
    setJwt(2, ['salesperson']); window.sessionStorage.setItem('wms:tour-flow:2', JSON.stringify({ campaignId: 'cost-quote-receipt', stage: 'receipt-navigation' }));
    render(<MemoryRouter initialEntries={['/orders/example']}><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('menuitem', { name: /财务中心/ }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /收付款/ }));
    await waitFor(() => expect(window.sessionStorage.getItem('wms:tour-flow:2')).toBeNull());
});

test.each(['salesperson', 'finance', 'admin'])('retired full receipt campaign does not invite %s or expose its restart', async role => {
    setJwt(3, [role]); render(<MemoryRouter><App /></MemoryRouter>); await screen.findByRole('menuitem', { name: /财务中心/ });
    expect(screen.queryByRole('button', { name: '立即了解' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开新功能引导中心' })).not.toBeInTheDocument();
    expect(shouldAutoShowFeatureTour).not.toHaveBeenCalled();
});


function setViewport(width) {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => {
        const minWidth = /min-width:\s*([\d.]+)px/.exec(query);
        const maxWidth = /max-width:\s*([\d.]+)px/.exec(query);
        return {
            matches: (!minWidth || width >= Number(minWidth[1])) && (!maxWidth || width <= Number(maxWidth[1])),
            media: query, onchange: null, addListener: () => {}, removeListener: () => {},
            addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
        };
    } });
}

function LocationProbe() {
    return <span data-testid="current-path">{useLocation().pathname}</span>;
}

function renderNavigation(path, roles = ['admin']) {
    setJwt(8, roles);
    return render(<MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter>);
}

test.each([
    ['/orders/example', '订单管理', '订单列表'],
    ['/order-exceptions', '订单管理', '异常订单'],
    ['/packing-lists/example', '仓储管理', '装箱单列表'],
    ['/shipping-confirmation-drafts/example', '仓储管理', '装箱单列表'],
    ['/bonus-estimate', '个人中心', '奖金'],
])('deep link %s expands its tree group and highlights %s', async (path, group, leaf) => {
    renderNavigation(path);
    expect(await screen.findByRole('menuitem', { name: new RegExp(group) })).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('menuitem', { name: new RegExp(leaf) })).toHaveClass('ant-menu-item-selected');
    expect(screen.getByTestId('current-path')).toHaveTextContent(path);
});

test('a group toggles its children without navigating; a leaf navigates and stays selected', async () => {
    renderNavigation('/orders');
    fireEvent.click(await screen.findByRole('menuitem', { name: /客户管理/ }));
    expect(screen.getByTestId('current-path')).toHaveTextContent('/orders');
    fireEvent.click(await screen.findByRole('menuitem', { name: /客户列表/ }));
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent('/customers'));
    expect(screen.getByRole('menuitem', { name: /客户列表/ })).toHaveClass('ant-menu-item-selected');
});

test('returning to expanded sidebar restores the current group', async () => {
    renderNavigation('/order-exceptions');
    expect(await screen.findByRole('menuitem', { name: /异常订单/ })).toHaveClass('ant-menu-item-selected');
    fireEvent.click(screen.getByRole('button', { name: '收起菜单' }));
    fireEvent.click(await screen.findByRole('button', { name: '展开菜单' }));
    expect(await screen.findByRole('menuitem', { name: /订单管理/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menuitem', { name: /异常订单/ })).toHaveClass('ant-menu-item-selected');
});

test('mobile drawer expands the current group, retains worker labels, and closes on navigation', async () => {
    setViewport(375);
    renderNavigation('/packing-lists', ['worker']);
    fireEvent.click(await screen.findByRole('button', { name: '打开菜单' }));
    expect(await screen.findByRole('menuitem', { name: /仓储管理/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menuitem', { name: /我的装箱单/ })).toHaveClass('ant-menu-item-selected');
    expect(screen.queryByRole('menuitem', { name: /订单管理/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /管理中心/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: /创建装箱单/ }));
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent('/packing-list/new'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test('receipt-navigation event reveals the payments leaf inside its new group', async () => {
    renderNavigation('/orders', ['salesperson']);
    await screen.findByRole('menuitem', { name: /财务中心/ });
    fireEvent.click(screen.getByRole('button', { name: '收起菜单' }));
    fireEvent(window, new CustomEvent(FEATURE_TOUR_FLOW_EVENT, { detail: { stage: 'receipt-navigation' } }));
    expect(await screen.findByRole('menuitem', { name: /财务中心/ })).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('menuitem', { name: /收付款/ })).toHaveClass('tour-receipts-menu');
});
