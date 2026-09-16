import {
    COST_QUOTE_RECEIPT_TOUR,
    getCostQuoteReceiptChapter,
    getCostQuoteReceiptOnboardingFlow,
} from './featureTourConfig';
import {
    FEATURE_TOUR_SCHEMA_VERSION,
    clearFeatureTourFlow,
    decodeJwtPayload,
    getFeatureTourStorageKey,
    readFeatureTourFlow,
    readFeatureTourState,
    saveFeatureTourChapterState,
    saveFeatureTourFlow,
    shouldAutoShowFeatureTour,
} from './featureTourState';

const quoteChapter = getCostQuoteReceiptChapter('quote');

beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
});

test('auto window includes both configured boundaries and excludes dates outside them', () => {
    const base = {
        campaign: COST_QUOTE_RECEIPT_TOUR,
        chapter: quoteChapter,
        state: { schemaVersion: FEATURE_TOUR_SCHEMA_VERSION, campaigns: {} },
        userRoles: ['salesperson'],
    };

    expect(shouldAutoShowFeatureTour({ ...base, now: COST_QUOTE_RECEIPT_TOUR.autoStartAt })).toBe(true);
    expect(shouldAutoShowFeatureTour({ ...base, now: COST_QUOTE_RECEIPT_TOUR.autoEndAt })).toBe(true);
    expect(shouldAutoShowFeatureTour({ ...base, now: '2026-08-27T23:59:59+08:00' })).toBe(false);
    expect(shouldAutoShowFeatureTour({ ...base, now: '2026-10-27T00:00:00+08:00' })).toBe(false);
});

test('completed and dismissed chapters do not auto show again for the same version', () => {
    ['completed', 'dismissed'].forEach(status => {
        const state = {
            schemaVersion: FEATURE_TOUR_SCHEMA_VERSION,
            campaigns: {
                [COST_QUOTE_RECEIPT_TOUR.id]: {
                    chapters: {
                        [quoteChapter.id]: { version: quoteChapter.version, status },
                    },
                },
            },
        };
        expect(shouldAutoShowFeatureTour({
            campaign: COST_QUOTE_RECEIPT_TOUR,
            chapter: quoteChapter,
            state,
            userRoles: ['salesperson'],
            now: '2026-09-01T00:00:00+08:00',
        })).toBe(false);
    });
});

test('raising only one chapter version makes only that chapter eligible again', () => {
    const receiptChapter = getCostQuoteReceiptChapter('receiptEntry');
    const state = {
        schemaVersion: FEATURE_TOUR_SCHEMA_VERSION,
        campaigns: {
            [COST_QUOTE_RECEIPT_TOUR.id]: {
                chapters: {
                    [quoteChapter.id]: { version: 1, status: 'completed' },
                    [receiptChapter.id]: { version: 1, status: 'completed' },
                },
            },
        },
    };
    const upgradedQuote = { ...quoteChapter, version: 2 };

    expect(shouldAutoShowFeatureTour({
        campaign: COST_QUOTE_RECEIPT_TOUR,
        chapter: upgradedQuote,
        state,
        userRoles: ['salesperson'],
        now: '2026-09-01T00:00:00+08:00',
    })).toBe(true);
    expect(shouldAutoShowFeatureTour({
        campaign: COST_QUOTE_RECEIPT_TOUR,
        chapter: receiptChapter,
        state,
        userRoles: ['salesperson'],
        now: '2026-09-01T00:00:00+08:00',
    })).toBe(false);
});

test('state is isolated by user and malformed storage safely falls back', () => {
    const firstUser = '11';
    const secondUser = '12';
    window.localStorage.setItem(getFeatureTourStorageKey(firstUser), '{broken json');
    expect(readFeatureTourState(firstUser)).toEqual({
        schemaVersion: FEATURE_TOUR_SCHEMA_VERSION,
        campaigns: {},
    });

    expect(saveFeatureTourChapterState({
        userId: firstUser,
        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
        chapterId: quoteChapter.id,
        version: quoteChapter.version,
        status: 'completed',
        now: '2026-09-01T01:02:03+08:00',
    })).toBe(true);

    expect(readFeatureTourState(firstUser).campaigns[COST_QUOTE_RECEIPT_TOUR.id]
        .chapters[quoteChapter.id].status).toBe('completed');
    expect(readFeatureTourState(secondUser).campaigns).toEqual({});
});

test('a storage write failure is reported without throwing', () => {
    const failingStorage = {
        getItem: () => null,
        setItem: () => { throw new Error('quota exceeded'); },
    };

    expect(saveFeatureTourChapterState({
        userId: '20',
        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
        chapterId: quoteChapter.id,
        version: quoteChapter.version,
        status: 'completed',
        storage: failingStorage,
    })).toBe(false);
});

test('JWT payload decoding supports base64url payloads and invalid values', () => {
    const payload = { user_id: 8, roles: ['finance'] };
    const encoded = window.btoa(JSON.stringify(payload))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');

    expect(decodeJwtPayload(`header.${encoded}.signature`)).toEqual(payload);
    expect(decodeJwtPayload('not-a-jwt')).toBeNull();
});

test('cross-route workflow stages are stored per user for the current browser session', () => {
    expect(saveFeatureTourFlow({
        userId: '31',
        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
        stage: 'select-quote-order',
    })).toBe(true);
    expect(readFeatureTourFlow('31')).toMatchObject({
        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
        stage: 'select-quote-order',
    });
    expect(readFeatureTourFlow('32')).toBeNull();
    expect(saveFeatureTourFlow({
        userId: '31',
        campaignId: COST_QUOTE_RECEIPT_TOUR.id,
        stage: 'unknown-stage',
    })).toBe(false);
    expect(clearFeatureTourFlow('31')).toBe(true);
    expect(readFeatureTourFlow('31')).toBeNull();
});

test('the campaign chooses the correct first workflow stage for each role', () => {
    expect(getCostQuoteReceiptOnboardingFlow(['salesperson'])).toMatchObject({
        startStage: 'select-quote-order',
        startPath: '/orders',
    });
    expect(getCostQuoteReceiptOnboardingFlow(['finance'])).toMatchObject({
        startStage: 'receipt-audit',
        startPath: '/finance',
    });
    expect(getCostQuoteReceiptOnboardingFlow(['admin'])).toMatchObject({
        startStage: 'select-quote-order',
        startPath: '/orders',
    });
    expect(getCostQuoteReceiptOnboardingFlow(['admin', 'salesperson'])).toMatchObject({
        role: 'salesperson',
        startStage: 'select-quote-order',
    });
    expect(getCostQuoteReceiptOnboardingFlow(['worker'])).toBeNull();
});
