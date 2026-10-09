export const FEATURE_TOUR_SCHEMA_VERSION = 1;
export const FEATURE_TOUR_STORAGE_PREFIX = 'wms:tour-state:';
export const FEATURE_TOUR_FLOW_STORAGE_PREFIX = 'wms:tour-flow:';
export const FEATURE_TOUR_FLOW_EVENT = 'wms:feature-tour-flow-change';
const FEATURE_TOUR_FLOW_STAGES = new Set([
    'select-quote-order',
    'quote',
    'receipt-navigation',
    'receipt-entry',
    'receipt-audit',
    'receivable-ledger',
]);

export function decodeJwtPayload(jwt) {
    if (!jwt || typeof jwt !== 'string') return null;

    try {
        const parts = jwt.split('.');
        if (parts.length !== 3) return null;
        const normalized = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        return JSON.parse(window.atob(padded));
    } catch (error) {
        return null;
    }
}

export function getCurrentTourUser(storage = window.localStorage) {
    const payload = decodeJwtPayload(storage.getItem('jwt'));
    const userId = payload?.user_id ?? payload?.id ?? payload?.uid;
    const roles = payload?.roles || (payload?.role ? [payload.role] : []);

    return {
        userId: userId === undefined || userId === null ? null : String(userId),
        roles: Array.isArray(roles) ? roles : [roles],
    };
}

export function getFeatureTourStorageKey(userId) {
    if (userId === undefined || userId === null || userId === '') return null;
    return `${FEATURE_TOUR_STORAGE_PREFIX}${userId}`;
}

export function getFeatureTourFlowStorageKey(userId) {
    if (userId === undefined || userId === null || userId === '') return null;
    return `${FEATURE_TOUR_FLOW_STORAGE_PREFIX}${userId}`;
}

export function createEmptyFeatureTourState() {
    return {
        schemaVersion: FEATURE_TOUR_SCHEMA_VERSION,
        campaigns: {},
    };
}

export function readFeatureTourState(userId, storage = window.localStorage) {
    const key = getFeatureTourStorageKey(userId);
    if (!key) return createEmptyFeatureTourState();

    try {
        const parsed = JSON.parse(storage.getItem(key));
        if (!parsed || typeof parsed !== 'object' || parsed.schemaVersion !== FEATURE_TOUR_SCHEMA_VERSION) {
            return createEmptyFeatureTourState();
        }
        return {
            ...parsed,
            campaigns: parsed.campaigns && typeof parsed.campaigns === 'object' ? parsed.campaigns : {},
        };
    } catch (error) {
        return createEmptyFeatureTourState();
    }
}

export function getSavedChapterState(state, campaignId, chapterId) {
    return state?.campaigns?.[campaignId]?.chapters?.[chapterId] || null;
}

export function isFeatureTourChapterHandled(state, campaignId, chapter) {
    const saved = getSavedChapterState(state, campaignId, chapter?.id);
    return Boolean(saved
        && saved.version === chapter?.version
        && (saved.status === 'completed' || saved.status === 'dismissed'));
}

export function isTourRoleAllowed(chapter, userRoles) {
    const allowedRoles = chapter?.roles || [];
    const roles = Array.isArray(userRoles) ? userRoles : [userRoles];
    return allowedRoles.some(role => roles.includes(role));
}

export function isTourInAutoWindow(campaign, now = new Date()) {
    if (!campaign?.enabled) return false;
    const timestamp = now instanceof Date ? now.getTime() : new Date(now).getTime();
    if (!Number.isFinite(timestamp)) return false;

    const start = campaign.autoStartAt ? new Date(campaign.autoStartAt).getTime() : null;
    const end = campaign.autoEndAt ? new Date(campaign.autoEndAt).getTime() : null;
    if (start !== null && timestamp < start) return false;
    if (end !== null && timestamp > end) return false;
    return true;
}

export function shouldAutoShowFeatureTour({ campaign, chapter, state, userRoles, now = new Date() }) {
    if (!chapter || !isTourRoleAllowed(chapter, userRoles) || !isTourInAutoWindow(campaign, now)) {
        return false;
    }

    return !isFeatureTourChapterHandled(state, campaign.id, chapter);
}

export function readFeatureTourFlow(userId, storage = window.sessionStorage) {
    const key = getFeatureTourFlowStorageKey(userId);
    if (!key) return null;

    try {
        const parsed = JSON.parse(storage.getItem(key));
        if (!parsed || !FEATURE_TOUR_FLOW_STAGES.has(parsed.stage)) return null;
        return parsed;
    } catch (error) {
        return null;
    }
}

export function saveFeatureTourFlow({
    userId,
    campaignId,
    stage,
    storage = window.sessionStorage,
}) {
    const key = getFeatureTourFlowStorageKey(userId);
    if (!key || !FEATURE_TOUR_FLOW_STAGES.has(stage)) return false;

    try {
        storage.setItem(key, JSON.stringify({
            campaignId,
            stage,
            updatedAt: new Date().toISOString(),
        }));
        window.dispatchEvent(new CustomEvent(FEATURE_TOUR_FLOW_EVENT, { detail: { stage } }));
        return true;
    } catch (error) {
        return false;
    }
}

export function clearFeatureTourFlow(userId, storage = window.sessionStorage) {
    const key = getFeatureTourFlowStorageKey(userId);
    if (!key) return false;

    try {
        storage.removeItem(key);
        window.dispatchEvent(new CustomEvent(FEATURE_TOUR_FLOW_EVENT, { detail: { stage: null } }));
        return true;
    } catch (error) {
        return false;
    }
}

export function saveFeatureTourChapterState({
    userId,
    campaignId,
    chapterId,
    version,
    status,
    now = new Date(),
    storage = window.localStorage,
}) {
    const key = getFeatureTourStorageKey(userId);
    if (!key || !['completed', 'dismissed'].includes(status)) return false;

    try {
        const current = readFeatureTourState(userId, storage);
        const campaign = current.campaigns?.[campaignId] || {};
        const chapters = campaign.chapters && typeof campaign.chapters === 'object' ? campaign.chapters : {};
        const next = {
            ...current,
            schemaVersion: FEATURE_TOUR_SCHEMA_VERSION,
            campaigns: {
                ...current.campaigns,
                [campaignId]: {
                    ...campaign,
                    chapters: {
                        ...chapters,
                        [chapterId]: {
                            version,
                            status,
                            updatedAt: (now instanceof Date ? now : new Date(now)).toISOString(),
                        },
                    },
                },
            },
        };
        storage.setItem(key, JSON.stringify(next));
        return true;
    } catch (error) {
        return false;
    }
}
