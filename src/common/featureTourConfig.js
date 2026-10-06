import React from 'react';

export const COST_QUOTE_RECEIPT_TOUR = {
    id: 'cost-quote-receipt',
    name: '成本报价与收款管理',
    summary: '了解订单报价、收款登记、财务审核与应收账款查询的新流程。',
    enabled: false,
    autoStartAt: '2026-08-28T00:00:00+08:00',
    autoEndAt: '2026-10-26T23:59:59+08:00',
    onboardingFlows: {
        salesperson: {
            role: 'salesperson',
            startStage: 'select-quote-order',
            startPath: '/orders',
            description: '选择一笔由你负责的订单，依次了解订单报价和收款登记。',
        },
        finance: {
            role: 'finance',
            startStage: 'receipt-audit',
            startPath: '/finance',
            description: '依次了解收款审核和应收账款台账。',
        },
        admin: {
            role: 'admin',
            startStage: 'select-quote-order',
            startPath: '/orders',
            description: '选择一笔由你负责的订单，依次了解订单报价和收款登记。',
        },
    },
    chapters: {
        workflowStart: {
            id: 'workflow-start',
            version: 1,
            roles: ['salesperson', 'finance', 'admin'],
            steps: [
                {
                    key: 'start',
                    title: '了解成本报价与收款管理',
                    description: '系统会根据你的角色，从对应的业务环节开始介绍新流程。',
                },
            ],
        },
        selectQuoteOrder: {
            id: 'select-quote-order',
            version: 1,
            roles: ['salesperson'],
            steps: [
                {
                    key: 'orders',
                    title: '请选择由你负责的订单',
                    description: (
                        <span>
                            请务必选择 <strong>由你负责的订单</strong>，点击订单号或“详情”后才能继续报价引导。
                        </span>
                    ),
                },
            ],
        },
        quote: {
            id: 'quote',
            version: 1,
            roles: ['salesperson'],
            steps: [
                {
                    key: 'entry',
                    title: '从订单发起报价',
                    description: '当前订单的负责业务员可以在这里打开报价窗口。',
                },
                {
                    key: 'summary',
                    title: '确认报价基础',
                    description: '先核对运输方式、最低单价和当前计费重量，应收账款会随报价实时计算。',
                },
                {
                    key: 'pricing',
                    title: '填写单价与附加费',
                    description: '录入每公斤单价、附加费和必要的报价说明。低于限价的报价会进入审核。',
                },
                {
                    key: 'submit',
                    title: '提交报价',
                    description: '确认预计应收无误后提交。Tour 只会说明操作，不会代替你提交数据。',
                },
                {
                    key: 'history',
                    title: '查看报价版本',
                    description: '报价历史会保留每个版本、应收金额和有效状态；最终采纳的报价可用于打印报价单。',
                },
                {
                    key: 'receiptMenu',
                    autoOnly: true,
                    title: '前往收付款',
                    description: '在左侧“收付款”登记实际资金，可不关联订单。参考订单仅作备注，财务确认后独立核销。',
                    nextButtonProps: { children: '前往收付款' },
                },
            ],
        },
        receiptEntry: {
            id: 'receipt-entry',
            version: 1,
            roles: ['salesperson', 'admin'],
            steps: [
                {
                    key: 'basics',
                    tab: 'entry',
                    title: '登记实际收付款',
                    description: '选择客户、资金方向、账户、日期和金额，可以保存草稿或提交财务。',
                },
                {
                    key: 'orders',
                    tab: 'entry',
                    title: '可选参考订单',
                    description: '可备注该客户的任意订单，包括空订单；参考订单不会自动核销，也可不选择订单。',
                },
                {
                    key: 'submit',
                    tab: 'entry',
                    title: '提交财务确认',
                    description: '提交后由另一位财务人员核对实际资金。确认、退回与核销都沿用这张收付款记录。',
                },
                {
                    key: 'records',
                    tab: 'list',
                    title: '跟踪收付款状态',
                    description: '记录中可查看草稿、待财务确认、已生效等状态；退回后在原记录修改并重新提交。',
                },
            ],
        },
        receiptAudit: {
            id: 'receipt-audit',
            version: 1,
            roles: ['finance', 'admin'],
            steps: [
                {
                    key: 'filter',
                    title: '筛选待审核收款单',
                    description: '默认显示待审核记录，也可切换查看已生效、已驳回或全部记录。',
                },
                {
                    key: 'details',
                    title: '核对收款分配',
                    description: '展开收款单可查看订单应收、此前已收、本次收款和收款后余额。',
                },
                {
                    key: 'review',
                    title: '审核通过或驳回',
                    description: '确认到账后审核通过；如需驳回，必须填写审核意见。Tour 不会执行审核操作。',
                },
            ],
        },
        receivableLedger: {
            id: 'receivable-ledger',
            version: 1,
            roles: ['finance', 'admin'],
            steps: [
                {
                    key: 'filters',
                    title: '查询应收账款',
                    description: '可按截止日期、订单或客户、报价负责人和结清状态筛选。',
                },
                {
                    key: 'totals',
                    title: '查看账款汇总',
                    description: '这里汇总当前筛选范围的应收、已收、未收和待审核占用金额。',
                },
                {
                    key: 'ledger',
                    title: '查看订单级明细',
                    description: '每行对应一笔订单的应收明细。“待重报”表示报价已因重量变化失效，需要业务员重新报价。',
                },
            ],
        },
    },
};

export function getCostQuoteReceiptChapter(chapterName) {
    return COST_QUOTE_RECEIPT_TOUR.chapters[chapterName];
}

export function getCostQuoteReceiptOnboardingFlow(userRoles) {
    const roles = Array.isArray(userRoles) ? userRoles : [userRoles];
    const priority = ['salesperson', 'admin', 'finance'];
    const role = priority.find(item => roles.includes(item));
    return role ? COST_QUOTE_RECEIPT_TOUR.onboardingFlows[role] : null;
}
