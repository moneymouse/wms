import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider, useLocation, useNavigate } from 'react-router-dom';
import 'whatwg-fetch';
import dayjs from 'dayjs';
import useUrlState from './useUrlState';

function Probe() {
    const [query, setQuery] = useUrlState('q', '');
    const [page, setPage] = useUrlState('page', 1, { validate: value => Number.isSafeInteger(value) && value > 0 });
    const [filters, setFilters] = useUrlState('filters', { status: 'pending' });
    const [optional, setOptional] = useUrlState('optional', undefined);
    const [statuses, setStatuses] = useUrlState('statuses', ['draft'], {
        encode: values => values.join(','), decode: raw => raw ? raw.split(',') : [],
    });
    const [dates, setDates] = useUrlState('dates', () => [dayjs('2026-10-01'), dayjs('2026-10-29')], {
        encode: values => JSON.stringify(values?.map(value => value.format('YYYY-MM-DD')) ?? null),
        decode: raw => JSON.parse(raw)?.map(value => dayjs(value)) ?? null,
    });
    const location = useLocation();
    const navigate = useNavigate();
    const firstFilters = React.useRef(filters);
    return <>
        <input aria-label="controlled search" value={query} onChange={event => setQuery(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') setQuery(event.currentTarget.value); }} />
        <output data-testid="values">{JSON.stringify({ query, page, filters, optional, statuses, dates: dates?.map(value => value.format('YYYY-MM-DD')) ?? null })}</output>
        <output data-testid="location">{JSON.stringify(location)}</output>
        <output data-testid="identity">{String(firstFilters.current === filters)}</output>
        <button onClick={() => { setQuery('客户 甲'); setPage(previous => previous + 1); setPage(previous => previous + 1); setFilters(previous => ({ ...previous, owner: 7 })); }}>batch</button>
        <button onClick={() => setQuery('new search')}>search</button>
        <button onClick={() => { setQuery(''); setPage(1); setFilters({ status: 'pending' }); }}>reset</button>
        <button onClick={() => setOptional('posted')}>optional</button>
        <button onClick={() => setStatuses([])}>clear statuses</button>
        <button onClick={() => setDates(null)}>clear dates</button>
        <button onClick={() => navigate(-1)}>back</button>
        <button onClick={() => navigate(1)}>forward</button>
        <button onClick={() => navigate('/orders?q=second&page=4')}>next entry</button>
        <button onClick={() => { setQuery('stale'); navigate('/different?keep=new'); }}>filter then leave</button>
    </>;
}

function values() { return JSON.parse(screen.getByTestId('values').textContent); }
function location() { return JSON.parse(screen.getByTestId('location').textContent); }

test('restores typed filters, optional identifiers and date codecs from an existing URL', () => {
    const params = new URLSearchParams({ q: '客户乙', page: '3', filters: JSON.stringify({ status: 'posted', owner: 9 }), optional: '42', dates: JSON.stringify(['2026-09-01', '2026-09-30']) });
    render(<MemoryRouter initialEntries={[`/orders?${params}`]}><Probe /></MemoryRouter>);
    expect(values()).toEqual({ query: '客户乙', page: 3, filters: { status: 'posted', owner: 9 }, optional: 42, statuses: ['draft'], dates: ['2026-09-01', '2026-09-30'] });
});

test('batches independent and functional updates while retaining unknown parameters, hash and navigation state', async () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/orders', search: '?keep=existing', hash: '#table', state: { paymentContext: { orderUid: 'abc' } } }]}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('batch'));
    await waitFor(() => expect(new URLSearchParams(location().search).get('page')).toBe('3'));
    expect(values()).toMatchObject({ query: '客户 甲', filters: { status: 'pending', owner: 7 } });
    const current = location();
    const params = new URLSearchParams(current.search);
    expect(params.get('keep')).toBe('existing');
    expect(params.get('q')).toBe('客户 甲');
    expect(params.get('page')).toBe('3');
    expect(JSON.parse(params.get('filters'))).toEqual({ status: 'pending', owner: 7 });
    expect(current.hash).toBe('#table');
    expect(current.state).toEqual({ paymentContext: { orderUid: 'abc' } });
    fireEvent.click(screen.getByText('reset'));
    await waitFor(() => expect(location().search).toBe('?keep=existing'));
});

test('keeps filter object identity stable when an unrelated parameter changes', async () => {
    render(<MemoryRouter initialEntries={['/orders?filters=%7B%22owner%22%3A7%7D']}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('search'));
    await waitFor(() => expect(values().query).toBe('new search'));
    expect(screen.getByTestId('identity')).toHaveTextContent('true');
});

test('restores URL state on browser back and forward navigation', async () => {
    render(<MemoryRouter initialEntries={['/orders?q=first&page=2']}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('next entry'));
    await waitFor(() => expect(values()).toMatchObject({ query: 'second', page: 4 }));
    fireEvent.click(screen.getByText('back'));
    await waitFor(() => expect(values()).toMatchObject({ query: 'first', page: 2 }));
    fireEvent.click(screen.getByText('forward'));
    await waitFor(() => expect(values()).toMatchObject({ query: 'second', page: 4 }));
});

test('replaces the current search entry so leaving a filtered page still returns to the previous page', async () => {
    render(<MemoryRouter initialEntries={['/orders?q=previous', '/orders?q=current']} initialIndex={1}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('search'));
    await waitFor(() => expect(values().query).toBe('new search'));
    fireEvent.click(screen.getByText('back'));
    await waitFor(() => expect(values().query).toBe('previous'));
    fireEvent.click(screen.getByText('forward'));
    await waitFor(() => expect(values().query).toBe('new search'));
});

test('uses defaults for malformed JSON, incorrect types and invalid page values', () => {
    render(<MemoryRouter initialEntries={['/orders?page=-4&filters=bad-json']}><Probe /></MemoryRouter>);
    expect(values()).toMatchObject({ page: 1, filters: { status: 'pending' } });
});

test('round-trips explicitly cleared values instead of restoring nonempty defaults', async () => {
    render(<MemoryRouter initialEntries={['/orders']}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('clear statuses'));
    fireEvent.click(screen.getByText('clear dates'));
    fireEvent.click(screen.getByText('optional'));
    await waitFor(() => expect(new URLSearchParams(location().search).get('optional')).toBe('posted'));
    expect(values()).toMatchObject({ statuses: [], dates: null, optional: 'posted' });
    const params = new URLSearchParams(location().search);
    expect(params.has('statuses')).toBe(true);
    expect(params.get('statuses')).toBe('');
    expect(params.get('dates')).toBe('null');
});

test('supports a router basename when updating only query state', async () => {
    render(<MemoryRouter basename="/wms" initialEntries={['/wms/orders?keep=1']}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('search'));
    await waitFor(() => expect(values().query).toBe('new search'));
    expect(location().pathname).toBe('/orders');
    expect(new URLSearchParams(location().search).get('keep')).toBe('1');
});

test('supports isolated reusable components without a router', () => {
    function Standalone() {
        const [page, setPage] = useUrlState('page', 1);
        return <button onClick={() => setPage(previous => previous + 1)}>{page}</button>;
    }
    render(<Standalone />);
    fireEvent.click(screen.getByText('1'));
    expect(screen.getByText('2')).toBeInTheDocument();
});

test('a navigation in the same event supersedes the previous page filter batch', async () => {
    render(<MemoryRouter initialEntries={['/orders?q=current']}><Probe /></MemoryRouter>);
    fireEvent.click(screen.getByText('filter then leave'));
    await act(async () => { await Promise.resolve(); });
    expect(location()).toMatchObject({ pathname: '/different', search: '?keep=new' });
    expect(values().query).toBe('');
});

test('works with a data router and retains a newer same-event navigation', async () => {
    const router = createMemoryRouter([{ path: '*', element: <Probe /> }], { initialEntries: ['/orders?keep=existing'] });
    render(<RouterProvider router={router} />);
    fireEvent.click(screen.getByText('batch'));
    await waitFor(() => expect(values()).toMatchObject({ page: 3, query: '客户 甲', filters: { status: 'pending', owner: 7 } }));
    expect(new URLSearchParams(router.state.location.search).get('keep')).toBe('existing');
    fireEvent.click(screen.getByText('filter then leave'));
    await act(async () => { await Promise.resolve(); });
    expect(router.state.location).toMatchObject({ pathname: '/different', search: '?keep=new' });
    expect(location()).toMatchObject({ pathname: '/different', search: '?keep=new' });
});

test('does not cancel a newer data-router navigation while its loader is pending', async () => {
    let finishLoading;
    const router = createMemoryRouter([
        { path: '/orders', element: <Probe /> },
        { path: '/different', element: <Probe />, loader: () => new Promise(resolve => { finishLoading = resolve; }) },
    ], { initialEntries: ['/orders?q=current'] });
    render(<RouterProvider router={router} />);
    fireEvent.click(screen.getByText('filter then leave'));
    await act(async () => { await Promise.resolve(); });
    expect(router.state.location.pathname).toBe('/orders');
    expect(router.state.navigation.location).toMatchObject({ pathname: '/different', search: '?keep=new' });
    await act(async () => { finishLoading(null); });
    await waitFor(() => expect(location()).toMatchObject({ pathname: '/different', search: '?keep=new' }));
});

test('keeps controlled input edits immediately and does not lose a same-tick Enter search', async () => {
    render(<MemoryRouter initialEntries={['/orders']}><Probe /></MemoryRouter>);
    const input = screen.getByRole('textbox', { name: 'controlled search' });
    fireEvent.change(input, { target: { value: '客户甲' } });
    expect(input).toHaveValue('客户甲');
    expect(values().query).toBe('客户甲');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(new URLSearchParams(location().search).get('q')).toBe('客户甲'));
    expect(input).toHaveValue('客户甲');
});

test('drops an uncommitted input mirror on navigation and does not revive it on forward navigation', async () => {
    render(<MemoryRouter initialEntries={['/orders?q=first', '/orders?q=second']} initialIndex={1}><Probe /></MemoryRouter>);
    const input = screen.getByRole('textbox', { name: 'controlled search' });
    fireEvent.change(input, { target: { value: 'uncommitted' } });
    expect(input).toHaveValue('uncommitted');
    fireEvent.click(screen.getByText('back'));
    await act(async () => { await Promise.resolve(); });
    expect(input).toHaveValue('first');
    fireEvent.click(screen.getByText('forward'));
    expect(input).toHaveValue('second');
    expect(new URLSearchParams(location().search).get('q')).toBe('second');
});

test('committing an optimistic object does not trigger effects a second time for the same filter', async () => {
    const changed = jest.fn();
    function ObjectProbe() {
        const [filters, setFilters] = useUrlState('filters', { status: 'pending' });
        const currentLocation = useLocation();
        React.useEffect(() => { changed(filters); }, [filters]);
        return <><button onClick={() => setFilters({ status: 'posted' })}>change object</button><output data-testid="object-url">{currentLocation.search}</output></>;
    }
    render(<MemoryRouter initialEntries={['/orders']}><ObjectProbe /></MemoryRouter>);
    expect(changed).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('change object'));
    expect(changed).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByTestId('object-url').textContent).toContain('posted'));
    expect(changed).toHaveBeenCalledTimes(2);
});
