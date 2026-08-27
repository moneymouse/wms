import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import App from './App';

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: query => ({
            matches: true,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
        }),
    });
});

test('renders the authenticated application menu', async () => {
    const payload = window.btoa(JSON.stringify({
        user_id: 1,
        name: 'Admin Test',
        roles: ['admin'],
    }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);

    render(<MemoryRouter initialEntries={['/receipts']}><App/></MemoryRouter>);

    expect(await screen.findByText('收款管理')).toBeInTheDocument();
    window.localStorage.removeItem('jwt');
});
