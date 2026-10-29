import { decodeJwtPayload } from './featureTourState';
import { getUserRoles, hasPermission, routePermissions } from './roleConfig';

const STORAGE_PREFIX = 'wms:list-url:v1:';
const LIST_PATHS = new Set([
    '/orders', '/order-exceptions', '/packing-lists', '/customers',
    '/shipping-confirmation-drafts', '/receipts', '/finance', '/cost-management',
    '/logs', '/audit-logs', '/admin', '/storage-management', '/work-details', '/bonus',
]);
const DETAIL_PARAMETERS = ['payment_id', 'exception_uid'];
const listPath = pathname => pathname === '/bonus-estimate' ? '/bonus' : pathname;
const validPart = (value, prefix) => typeof value === 'string' && value.length <= 65536
    && (!value || value.startsWith(prefix)) && !/[\r\n]/.test(value);

function listSearch(search) {
    const params = new URLSearchParams(search);
    if (!DETAIL_PARAMETERS.some(parameter => params.has(parameter))) return search;
    DETAIL_PARAMETERS.forEach(parameter => params.delete(parameter));
    return params.toString() ? `?${params}` : '';
}

function storageKey(pathname, user) {
    const userId = user?.userId;
    if ((typeof userId !== 'string' && typeof userId !== 'number') || !/^[A-Za-z0-9_-]{1,128}$/.test(String(userId))) return null;
    if (typeof userId === 'number' && (!Number.isSafeInteger(userId) || userId <= 0)) return null;
    if (!LIST_PATHS.has(pathname) || !hasPermission(user.roles || [], routePermissions[pathname] || [])) return null;
    return `${STORAGE_PREFIX}${encodeURIComponent(String(userId))}:${pathname}`;
}

/** Read the actor at navigation time, so a prior account's UI state is never reused. */
export function getListNavigationUser(storage) {
    try {
        const payload = decodeJwtPayload((storage || window.localStorage).getItem('jwt'));
        return { userId: payload?.user_id ?? payload?.id ?? payload?.uid, roles: getUserRoles(payload || {}) };
    } catch (error) {
        return { userId: null, roles: [] };
    }
}

/** Remember list URLs only. Form/navigation state is deliberately never serialized. */
export function rememberListLocation(location, user, storage) {
    const pathname = listPath(location?.pathname);
    const key = storageKey(pathname, user);
    if (!key) return false;
    const search = location.search || '';
    const hash = location.hash || '';
    if (!validPart(search, '?') || !validPart(hash, '#')) return false;
    try {
        (storage || window.sessionStorage).setItem(key, JSON.stringify({ pathname, search: listSearch(search), hash }));
        return true;
    } catch (error) {
        return false;
    }
}

/** Only explicit menu navigation calls this; direct URLs retain their own filters. */
export function getRememberedListUrl(pathname, user, storage) {
    const canonicalPath = listPath(pathname);
    const key = storageKey(canonicalPath, user);
    if (!key) return pathname;
    try {
        const saved = JSON.parse((storage || window.sessionStorage).getItem(key));
        if (!saved || saved.pathname !== canonicalPath || !validPart(saved.search, '?') || !validPart(saved.hash, '#')) return pathname;
        return `${canonicalPath}${listSearch(saved.search)}${saved.hash}`;
    } catch (error) {
        return pathname;
    }
}
