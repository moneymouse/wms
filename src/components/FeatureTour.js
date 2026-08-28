import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Space, Tooltip, Tour } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';

import { COST_QUOTE_RECEIPT_TOUR } from '../common/featureTourConfig';
import {
    getCurrentTourUser,
    readFeatureTourState,
    saveFeatureTourChapterState,
    shouldAutoShowFeatureTour,
} from '../common/featureTourState';

export default function FeatureTour({
    chapter,
    steps,
    autoSteps,
    manualSteps,
    eligible = true,
    autoEnabled = true,
    forceAutoStart = false,
    showTrigger = true,
    persistOnFinish = true,
    persistOnDismiss = true,
    onStepChange,
    onTourEnd,
    onStart,
    triggerAriaLabel = '打开操作引导',
}) {
    const [open, setOpen] = useState(false);
    const [current, setCurrent] = useState(0);
    const [mode, setMode] = useState('auto');
    const attemptedAutoOpen = useRef(false);
    const finishing = useRef(false);
    const { userId, roles } = getCurrentTourUser();
    const roleAllowed = chapter?.roles?.some(role => roles.includes(role));
    const canUseTour = Boolean(chapter && eligible && roleAllowed);
    const activeSteps = mode === 'manual'
        ? (manualSteps || steps)
        : (autoSteps || steps);

    const persist = useCallback((status) => {
        saveFeatureTourChapterState({
            userId,
            campaignId: COST_QUOTE_RECEIPT_TOUR.id,
            chapterId: chapter.id,
            version: chapter.version,
            status,
        });
    }, [chapter, userId]);

    const startTour = useCallback(async (nextMode) => {
        if (!canUseTour) return;
        setMode(nextMode);
        setCurrent(0);
        onStart?.(nextMode);
        if (onStepChange) await onStepChange(0, -1, nextMode);
        setOpen(true);
    }, [canUseTour, onStart, onStepChange]);

    useEffect(() => {
        if (!canUseTour || attemptedAutoOpen.current) return;
        if (!forceAutoStart && !autoEnabled) return;
        attemptedAutoOpen.current = true;
        const state = readFeatureTourState(userId);
        if (forceAutoStart || shouldAutoShowFeatureTour({
            campaign: COST_QUOTE_RECEIPT_TOUR,
            chapter,
            state,
            userRoles: roles,
        })) {
            startTour('auto');
        }
    }, [autoEnabled, canUseTour, chapter, forceAutoStart, roles, startTour, userId]);

    const finish = () => {
        finishing.current = true;
        if (persistOnFinish) persist('completed');
        setOpen(false);
        onTourEnd?.('completed', mode);
        window.setTimeout(() => { finishing.current = false; }, 0);
    };

    const dismiss = () => {
        if (finishing.current) return;
        if (persistOnDismiss) persist('dismissed');
        setOpen(false);
        onTourEnd?.('dismissed', mode);
    };

    const changeStep = async (nextCurrent) => {
        if (onStepChange) await onStepChange(nextCurrent, current, mode);
        setCurrent(nextCurrent);
    };

    if (!canUseTour) return null;

    return (
        <>
            {showTrigger && <Tooltip title="操作引导">
                    <Button
                        type="text"
                        size="small"
                        icon={<QuestionCircleOutlined />}
                        aria-label={triggerAriaLabel}
                        onClick={() => startTour('manual')}
                    />
                </Tooltip>}
            <Tour
                open={open}
                current={current}
                steps={activeSteps}
                onChange={changeStep}
                onClose={dismiss}
                onFinish={finish}
                disabledInteraction={false}
                actionsRender={(originNode) => (
                    <Space size={4}>
                        <Button type="link" size="small" onClick={dismiss}>跳过</Button>
                        {originNode}
                    </Space>
                )}
            />
        </>
    );
}
