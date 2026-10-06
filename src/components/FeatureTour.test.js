import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import FeatureTour from './FeatureTour';
import { COST_QUOTE_RECEIPT_TOUR, getCostQuoteReceiptChapter } from '../common/featureTourConfig';
import { readFeatureTourState } from '../common/featureTourState';

jest.mock('antd', () => {
    const actual = jest.requireActual('antd');
    return {
        ...actual,
        Tooltip: ({ children }) => children,
        Tour: ({ open, steps, current, onClose, onFinish }) => open ? (
            <div data-testid="tour-panel">
                <span>{steps[current]?.title}</span>
                <button onClick={() => onClose(current)}>跳过测试</button>
                <button onClick={onFinish}>完成测试</button>
            </div>
        ) : null,
    };
});

const quoteChapter = getCostQuoteReceiptChapter('quote');
const steps = quoteChapter.steps.map(step => ({ ...step, target: null }));

function setJwt(userId = 1, roles = ['salesperson']) {
    const payload = window.btoa(JSON.stringify({ user_id: userId, roles }));
    window.localStorage.setItem('jwt', `header.${payload}.signature`);
}

beforeEach(() => {
    COST_QUOTE_RECEIPT_TOUR.enabled = true;
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-09-01T00:00:00+08:00'));
    window.localStorage.clear();
    setJwt();
});

afterEach(() => {
    COST_QUOTE_RECEIPT_TOUR.enabled = false;
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
});

test('auto opens in the campaign window and completing persists the chapter version', () => {
    render(<FeatureTour chapter={quoteChapter} steps={steps} />);

    expect(screen.getByTestId('tour-panel')).toBeInTheDocument();
    fireEvent.click(screen.getByText('完成测试'));
    expect(screen.queryByTestId('tour-panel')).not.toBeInTheDocument();

    const state = readFeatureTourState('1');
    expect(state.campaigns[COST_QUOTE_RECEIPT_TOUR.id].chapters[quoteChapter.id]).toMatchObject({
        version: quoteChapter.version,
        status: 'completed',
    });
});

test('closing the tour persists dismissed and prevents a new automatic opening', () => {
    const first = render(<FeatureTour chapter={quoteChapter} steps={steps} />);
    fireEvent.click(screen.getByText('跳过测试'));
    first.unmount();

    render(<FeatureTour chapter={quoteChapter} steps={steps} />);
    expect(screen.queryByTestId('tour-panel')).not.toBeInTheDocument();
    expect(readFeatureTourState('1').campaigns[COST_QUOTE_RECEIPT_TOUR.id]
        .chapters[quoteChapter.id].status).toBe('dismissed');
});

test('after the campaign window it stays closed automatically but manual help still opens it', () => {
    jest.setSystemTime(new Date('2026-10-27T00:00:00+08:00'));
    render(<FeatureTour chapter={quoteChapter} steps={steps} />);

    expect(screen.queryByTestId('tour-panel')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开操作引导' }));
    expect(screen.getByTestId('tour-panel')).toBeInTheDocument();
});

test('users outside the chapter roles do not see the manual entry or automatic tour', () => {
    window.localStorage.clear();
    setJwt(2, ['finance']);
    render(<FeatureTour chapter={quoteChapter} steps={steps} />);

    expect(screen.queryByRole('button', { name: '打开操作引导' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('tour-panel')).not.toBeInTheDocument();
});

test('automatic onboarding and the question trigger can use different step sets', () => {
    const autoSteps = [{ title: '首次完整流程', target: null }];
    const manualSteps = [{ title: '当前页面操作', target: null }];
    const first = render(
        <FeatureTour
            chapter={quoteChapter}
            steps={autoSteps}
            autoSteps={autoSteps}
            manualSteps={manualSteps}
            forceAutoStart
        />
    );
    expect(screen.getByText('首次完整流程')).toBeInTheDocument();
    first.unmount();

    window.localStorage.clear();
    setJwt();
    render(
        <FeatureTour
            chapter={quoteChapter}
            steps={autoSteps}
            autoSteps={autoSteps}
            manualSteps={manualSteps}
            autoEnabled={false}
        />
    );
    fireEvent.click(screen.getByRole('button', { name: '打开操作引导' }));
    expect(screen.getByText('当前页面操作')).toBeInTheDocument();
});


test('retired campaign stays closed automatically while quote manual help remains usable', () => {
    COST_QUOTE_RECEIPT_TOUR.enabled = false;
    render(<FeatureTour chapter={quoteChapter} steps={steps} />);
    expect(screen.queryByTestId('tour-panel')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开操作引导' }));
    expect(screen.getByTestId('tour-panel')).toBeInTheDocument();
});
