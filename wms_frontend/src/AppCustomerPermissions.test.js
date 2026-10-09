import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import App from './App';

jest.mock('./common/featureTourState', () => ({
    ...jest.requireActual('./common/featureTourState'),
    shouldAutoShowFeatureTour: () => false,
}));

function LocationProbe() {
    return <span data-testid="current-path">{useLocation().pathname}</span>;
}

function renderCustomers(payload) {
    window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: 7, ...payload }))}.signature`);
    return render(<MemoryRouter initialEntries={['/customers']}><App /><LocationProbe /></MemoryRouter>);
}

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({
        matches: true, media: query, onchange: null,
        addListener: () => {}, removeListener: () => {}, addEventListener: () => {},
        removeEventListener: () => {}, dispatchEvent: () => false,
    }) });
});

test.each([
    { roles: ['salesperson'] },
    { roles: ['admin'] },
    { roles: ['store_manager'] },
    { roles: ['finance'], role: 'salesperson' },
    { role: 'salesperson' },
])('%j sees the customer menu and can enter its route', async payload => {
    renderCustomers(payload);
    expect(await screen.findByText('客户管理')).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent('/customers');
});

test.each([
    ['clerk', '/orders'],
    ['finance', '/finance'],
    ['worker', '/packing-lists'],
])('%s retains restricted customer access', async (role, landingPage) => {
    renderCustomers({ roles: [role] });
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent(landingPage));
    expect(screen.queryByText('客户管理')).not.toBeInTheDocument();
});
