import React, { useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Table, Tabs, Typography, message } from 'antd';

import FinanceCenter from './financeCenter';
import { ReceiptAudit, ReceivableLedger } from './financeReceivables';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';


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

export default function FinanceHub() {
    return <div style={{ padding: 24 }}>
        <Typography.Title level={3}>财务中心</Typography.Title>
        <Tabs items={[
            { key: 'receivable', label: '应收账款台账', children: <ReceivableLedger /> },
            { key: 'audit', label: '收款审核', children: <ReceiptAudit /> },
            { key: 'bonus', label: '奖金管理', children: <><SalesBonusRates /><FinanceCenter /></> },
        ]} />
    </div>;
}
