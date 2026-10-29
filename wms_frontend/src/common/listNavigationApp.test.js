import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import App from '../App';
import { rememberListLocation } from './listNavigation';

jest.mock('../components/MessageInbox', () => () => null);
jest.mock('./featureTourState', () => ({ ...jest.requireActual('./featureTourState'), shouldAutoShowFeatureTour: () => false }));

function LocationProbe() {
    const location = useLocation();
    return <output aria-label="当前页面">{`${location.pathname}${location.search}${location.hash}`}</output>;
}
async function expandGroup(name) {
    const group = await screen.findByRole('menuitem', { name });
    if (group.getAttribute('aria-expanded') !== 'true') fireEvent.click(group);
}
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear();
    window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: 7, roles: ['admin'] }))}.signature`);
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: query.includes('min-width') && !query.includes('1600'), media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});

test('sidebar returns to the last filters for that list', async () => {
    render(<MemoryRouter initialEntries={['/orders?search=XD-001&page=3#results']}><App /><LocationProbe /></MemoryRouter>);
    await expandGroup(/客户管理/);
    fireEvent.click(await screen.findByRole('menuitem', { name: /客户列表/ }));
    await waitFor(() => expect(screen.getByLabelText('当前页面')).toHaveTextContent('/customers'));
    await expandGroup(/订单管理/);
    fireEvent.click(await screen.findByRole('menuitem', { name: /订单列表/ }));
    await waitFor(() => expect(screen.getByLabelText('当前页面')).toHaveTextContent('/orders?search=XD-001&page=3#results'));
});

test('an explicit URL is never replaced by a saved filter on mount', async () => {
    rememberListLocation({ pathname: '/orders', search: '?search=old' }, { userId: 7, roles: ['admin'] });
    render(<MemoryRouter initialEntries={['/orders?search=explicit']}><App /><LocationProbe /></MemoryRouter>);
    await screen.findByRole('menuitem', { name: /订单列表/ });
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('/orders?search=explicit');
});

test('another account does not inherit the saved menu destination', async () => {
    rememberListLocation({ pathname: '/orders', search: '?search=private' }, { userId: 8, roles: ['admin'] });
    render(<MemoryRouter initialEntries={['/customers']}><App /><LocationProbe /></MemoryRouter>);
    await expandGroup(/订单管理/);
    fireEvent.click(await screen.findByRole('menuitem', { name: /订单列表/ }));
    await waitFor(() => expect(screen.getByLabelText('当前页面').textContent).toBe('/orders'));
});
