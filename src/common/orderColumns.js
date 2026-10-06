import React from 'react';
import { Button, Typography } from 'antd';
import orderProperty from './orderProperty';

export function buildOrderColumns({ properties = orderProperty, onOpenOrder, sortable = true, fixedColumnCount = 2 } = {}) {
    return properties.map((property, index) => ({
        key: property.name,
        title: property.label,
        dataIndex: property.name,
        width: index < fixedColumnCount ? 160 : property.width || 200,
        ellipsis: true,
        sorter: !sortable ? false : property.name === 'order_date' || property.name === 'update_date'
            ? {
                compare: (a, b) => new Date(a[property.name]).getTime() - new Date(b[property.name]).getTime(),
                multiple: 1,
            }
            : property.name === 'receiver_name' || property.name === 'customer_name'
                ? {
                    compare: (a, b) => (a[property.name] || '').localeCompare(b[property.name] || ''),
                    multiple: 2,
                }
                : false,
        fixed: index < fixedColumnCount ? 'left' : '',
        render: (text, record) => {
            if (text === undefined || text === null || text === '') return null;
            return <Typography.Text copyable>
                {property.name === 'order_id' && onOpenOrder
                    ? <Button type="link" onClick={() => onOpenOrder(record.uid)}>{text}</Button>
                    : text}
            </Typography.Text>;
        },
    }));
}
