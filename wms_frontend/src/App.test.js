import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { shouldAutoShowFeatureTour } from './common/featureTourState';

jest.mock('./common/featureTourState', () => ({ ...jest.requireActual('./common/featureTourState'), shouldAutoShowFeatureTour: jest.fn(() => true) }));
function setJwt(userId, roles, name = 'Test User') { window.localStorage.setItem('jwt', `header.${window.btoa(JSON.stringify({ user_id: userId, name, roles }))}.signature`); }
beforeEach(() => {
    window.localStorage.clear(); window.sessionStorage.clear(); shouldAutoShowFeatureTour.mockClear();
    Object.defineProperty(window, 'matchMedia', { writable: true, value: query => ({ matches: true, media: query, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }) });
});

test.each(['admin', 'salesperson', 'finance'])('%s can navigate to the unified payments page', async role => {
    setJwt(1, [role]); render(<MemoryRouter initialEntries={['/receipts']}><App /></MemoryRouter>);
    expect(await screen.findByText('收付款')).toBeInTheDocument();
    expect(screen.queryByText('收款管理')).not.toBeInTheDocument();
});

test('multi-role labels use spacing without punctuation separators', async () => {
    setJwt(11, ['admin', 'salesperson'], 'Multi Role Test'); render(<MemoryRouter><App /></MemoryRouter>);
    fireEvent.click((await screen.findByRole('img', { name: 'menu-unfold' })).closest('button'));
    expect(await screen.findByText('管理员')).toHaveStyle({ whiteSpace: 'nowrap' }); expect(screen.getByText('业务员')).toHaveStyle({ whiteSpace: 'nowrap' });
    expect(screen.queryByText('，')).not.toBeInTheDocument();
});

test('entering payments clears the retired order-selection receipt workflow', async () => {
    setJwt(2, ['salesperson']); window.sessionStorage.setItem('wms:tour-flow:2', JSON.stringify({ campaignId: 'cost-quote-receipt', stage: 'receipt-navigation' }));
    render(<MemoryRouter initialEntries={['/orders/example']}><App /></MemoryRouter>); fireEvent.click(await screen.findByText('收付款'));
    await waitFor(() => expect(window.sessionStorage.getItem('wms:tour-flow:2')).toBeNull());
});

test.each(['salesperson', 'finance', 'admin'])('retired full receipt campaign does not invite %s or expose its restart', async role => {
    setJwt(3, [role]); render(<MemoryRouter><App /></MemoryRouter>); await screen.findByText('收付款');
    expect(screen.queryByRole('button', { name: '立即了解' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开新功能引导中心' })).not.toBeInTheDocument();
    expect(shouldAutoShowFeatureTour).not.toHaveBeenCalled();
});
