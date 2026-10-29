import { useCallback, useContext, useMemo, useRef, useState } from 'react';
import { UNSAFE_DataRouterContext, UNSAFE_LocationContext, UNSAFE_NavigationContext } from 'react-router-dom';

// One transaction per router lets independent controls update query parameters in
// the same event without overwriting each other's changes.
const pendingUpdates = new WeakMap();

function encodeValue(value, options) {
    if (value === undefined) return undefined;
    if (options.encode) return options.encode(value);
    return typeof value === 'string' ? value : JSON.stringify(value);
}

function decodeValue(raw, initialValue, options) {
    if (raw === null) return initialValue;
    try {
        let value;
        if (options.decode) value = options.decode(raw);
        else if (typeof initialValue === 'string') value = raw;
        else {
            try { value = JSON.parse(raw); }
            catch (error) {
                // Optional Select values commonly start as undefined and later
                // contain either a string status or a numeric identifier.
                if (initialValue === undefined || initialValue === null) value = raw;
                else return initialValue;
            }
            if (typeof initialValue === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) return initialValue;
            if (typeof initialValue === 'boolean' && typeof value !== 'boolean') return initialValue;
            if (Array.isArray(initialValue) && value !== null && !Array.isArray(value)) return initialValue;
            if (initialValue && typeof initialValue === 'object' && !Array.isArray(initialValue)
                && (value === null || typeof value !== 'object' || Array.isArray(value))) return initialValue;
        }
        return options.validate && !options.validate(value) ? initialValue : value;
    } catch (error) {
        return initialValue;
    }
}

function sameLocation(left, right) {
    return left.key === right.key && left.pathname === right.pathname
        && left.search === right.search && left.hash === right.hash;
}

function readNavigation(dataRouterContext, navigator) {
    const routerState = dataRouterContext?.router?.state;
    return { location: routerState?.location || navigator.location, pendingLocation: routerState?.navigation?.location };
}

function sameOptionalLocation(left, right) {
    return left === right || Boolean(left && right && sameLocation(left, right));
}

/**
 * URL-backed useState for searches, filters, tabs and pagination.
 * Strings use readable query values; other values use JSON. Supply encode/decode
 * for dates or existing URL formats, and validate to reject invalid values.
 * Missing parameters restore the initial value. Undefined resets a parameter;
 * an empty string or null can explicitly represent a cleared filter.
 * Outside a router this behaves like useState, for reusable standalone panels.
 */
export default function useUrlState(key, defaultValue, options = {}) {
    const locationContext = useContext(UNSAFE_LocationContext);
    const navigationContext = useContext(UNSAFE_NavigationContext);
    const dataRouterContext = useContext(UNSAFE_DataRouterContext);
    const [localValue, setLocalValue] = useState(defaultValue);
    const initialValue = useRef(localValue).current;
    const optimistic = useRef(null);
    const location = locationContext?.location;
    const raw = location ? new URLSearchParams(location.search).get(key) : null;
    const optionsRef = useRef(options);
    optionsRef.current = options;
    // Depend on this parameter alone so changing a different tab's URL state
    // cannot recreate filter objects and retrigger data-loading effects.
    const value = useMemo(() => {
        const pending = optimistic.current;
        // Reuse the optimistic object when the router commits the same value.
        // A filter change then triggers data loading once, not again on commit.
        if (pending?.key === key && pending.raw === raw) return pending.value;
        return decodeValue(raw, initialValue, optionsRef.current);
    }, [raw, initialValue, key]);
    if (optimistic.current && (!location || optimistic.current.key !== key || !sameLocation(location, optimistic.current.location))) {
        optimistic.current = null;
    }
    const latest = useRef();
    latest.current = { location, navigationContext, dataRouterContext, key, initialValue };

    const setValue = useCallback(update => {
        const current = latest.current;
        const { navigator, basename = '/' } = current.navigationContext || {};
        if (!current.location || !navigator) {
            setLocalValue(update);
            return;
        }
        let transaction = pendingUpdates.get(navigator);
        if (!transaction || !sameLocation(transaction.location, current.location)) {
            transaction = {
                location: current.location, navigation: readNavigation(current.dataRouterContext, navigator),
                params: new URLSearchParams(current.location.search), scheduled: false,
            };
            pendingUpdates.set(navigator, transaction);
        }
        const settings = optionsRef.current;
        const previous = decodeValue(transaction.params.get(current.key), current.initialValue, settings);
        const next = typeof update === 'function' ? update(previous) : update;
        const encoded = encodeValue(next, settings);
        if (encoded === undefined || encoded === encodeValue(current.initialValue, settings)) transaction.params.delete(current.key);
        else transaction.params.set(current.key, encoded);
        const optimisticValue = next === undefined || (settings.validate && !settings.validate(next)) ? current.initialValue : next;
        optimistic.current = { location: current.location, key: current.key, raw: transaction.params.get(current.key), value: optimisticValue };
        // Controlled inputs must receive their new value before React restores
        // the DOM at the end of the event. URL persistence is batched below.
        setLocalValue(() => next);

        if (transaction.scheduled) return;
        transaction.scheduled = true;
        Promise.resolve().then(() => {
            if (pendingUpdates.get(navigator) !== transaction) return;
            pendingUpdates.delete(navigator);
            // Check the router itself as well as rendered context. A navigate()
            // in the same event may already have changed history, or started a
            // loader, before React renders the destination.
            if (!sameLocation(latest.current.location || {}, transaction.location)) return;
            const navigation = readNavigation(current.dataRouterContext, navigator);
            if (!sameOptionalLocation(navigation.location, transaction.navigation.location)
                || !sameOptionalLocation(navigation.pendingLocation, transaction.navigation.pendingLocation)) return;
            const query = transaction.params.toString();
            const search = query ? `?${query}` : '';
            if (search === transaction.location.search) return;
            const pathname = basename === '/' ? transaction.location.pathname
                : `${basename.replace(/\/$/, '')}/${transaction.location.pathname.replace(/^\//, '')}`;
            navigator.replace({ pathname, search, hash: transaction.location.hash }, transaction.location.state);
        });
    }, []);

    return [location ? (optimistic.current ? optimistic.current.value : value) : localValue, setValue];
}
