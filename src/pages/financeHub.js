import React, { useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Table, message } from 'antd';

import FinanceCenter from './financeCenter';
import FinanceWorkspace from './financeWorkspace';
import styles from './financeWorkspace.module.css';
import { ReceiptAudit } from './financeReceivables';
import FinanceOrderSettlements from './financeOrderSettlements';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { COST_QUOTE_RECEIPT_TOUR } from '../common/featureTourConfig';
import {
    FEATURE_TOUR_FLOW_EVENT,
    getCurrentTourUser,
    readFeatureTourFlow,
} from '../common/featureTourState';


function SalesBonusRates() {
    const [messageApi, contextHolder] = message.useMessage();
    const [form] = Form.useForm();
    const [rates, setRates] = useState([]);
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const fetchRates = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${endpoint}/finance/sales-bonus-rates`, { headers: getSafeHeader() });
            const result = await response.json();
            if (result.code === 200) setRates(result.data || []);
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { fetchRates(); }, []);

    const createRate = async () => {
        try {
            const values = await form.validateFields();
            setSubmitting(true);
            const response = await fetch(`${endpoint}/finance/sales-bonus-rates`, {
                method: 'POST',
                headers: { ...getSafeHeader(), 'Content-Type': 'application/json' },
                body: JSON.stringify(values),
            });
            const result = await response.json();
            if (!response.ok || result.code !== 200) throw new Error(result.msg || '保存失败');
            messageApi.success('费率版本已创建');
            form.resetFields();
            fetchRates();
        } catch (error) {
            if (error?.errorFields) return;
            messageApi.error(error.message || '保存失败');
        } finally {
            setSubmitting(false);
        }
    };

    return <Card title="跟单重量奖金费率" style={{ marginBottom: 16 }}>
        {contextHolder}
        <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
            <Form.Item name="effective_from" label="生效日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
            <Form.Item name="rate_per_kg" label="费率(CNY/kg)" rules={[{ required: true }]}><InputNumber min={0} precision={4} /></Form.Item>
            <Form.Item name="remark" label="说明"><Input style={{ width: 220 }} /></Form.Item>
            <Button type="primary" loading={submitting} onClick={createRate}>新增费率版本</Button>
        </Form>
        <Table rowKey="id" loading={loading} dataSource={rates} pagination={false} size="small" columns={[
            { title: '生效日期', dataIndex: 'effective_from' },
            { title: '费率(CNY/kg)', dataIndex: 'rate_per_kg', render: v => Number(v || 0).toFixed(4) },
            { title: '创建人', dataIndex: 'creator_name' },
            { title: '创建时间', dataIndex: 'create_date' },
            { title: '说明', dataIndex: 'remark' },
        ]} />
    </Card>;
}

export default function FinanceHub({ extraTabs = [] }) {
    const { userId: tourUserId } = getCurrentTourUser();
    const initialTourFlow = readFeatureTourFlow(tourUserId);
    const [activeTab, setActiveTab] = useState(
        initialTourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id
            && initialTourFlow.stage === 'receipt-audit'
            ? 'audit'
            : initialTourFlow?.campaignId === COST_QUOTE_RECEIPT_TOUR.id && initialTourFlow.stage === 'receivable-ledger'
                ? 'receivable'
                : 'overview'
    );

    useEffect(() => {
        const handleTourFlowChange = (event) => {
            if (event.detail?.stage === 'receipt-audit') setActiveTab('audit');
            if (event.detail?.stage === 'receivable-ledger') setActiveTab('receivable');
        };
        window.addEventListener(FEATURE_TOUR_FLOW_EVENT, handleTourFlowChange);
        return () => window.removeEventListener(FEATURE_TOUR_FLOW_EVENT, handleTourFlowChange);
    }, []);

    return <div className={styles.hub}>
        <FinanceWorkspace activeTab={activeTab} onTabChange={setActiveTab} extraTabs={[
            { key: 'receivable', label: '订单应收', children: <FinanceOrderSettlements /> },
            { key: 'audit', label: '历史收款清理', children: <ReceiptAudit /> },
            { key: 'bonus', label: '奖金', children: <><SalesBonusRates /><FinanceCenter /></> },
            ...extraTabs,
        ]} />
    </div>;
}
