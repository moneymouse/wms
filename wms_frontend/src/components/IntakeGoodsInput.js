import React, { useEffect, useRef, useState } from 'react';
import { AutoComplete, Button, Input, InputNumber, Popover } from 'antd';
import { DeleteOutlined, DownOutlined, PlusOutlined } from '@ant-design/icons';
import { emptyIntakeItemDetail, MAX_INTAKE_ITEMS, MAX_INTAKE_PIECE_COUNT } from '../common/intakeApi';
import styles from './IntakeGoodsInput.module.css';

const itemSummary = details => details.length === 1 && !details[0].item_name.trim() && (details[0].piece_count === null || details[0].piece_count === '')
    ? ''
    : details.map(row => `${row.item_name.trim() || '品名待填写'} x ${row.piece_count === null || row.piece_count === '' ? '待填写' : row.piece_count}`).join('、');

export default function IntakeGoodsInput({ boxIndex, details, options, disabled, onChange }) {
    const [open, setOpen] = useState(false);
    const summaryRef = useRef(null);
    const firstNameRef = useRef(null);
    const label = `第${boxIndex + 1}箱`;
    const dialogId = `intake-box-${boxIndex + 1}-goods`;
    const summary = itemSummary(details);

    useEffect(() => {
        if (disabled) setOpen(false);
    }, [disabled]);

    const close = () => {
        setOpen(false);
        summaryRef.current?.focus();
    };
    const updateItem = (index, field, value) => {
        if (!disabled) onChange(details.map((row, i) => i === index ? { ...row, [field]: value } : row));
    };
    const content = <section id={dialogId} className={styles.panel} role="dialog" aria-label={`${label}商品明细`} onKeyDown={event => {
        if (event.key === 'Escape') { event.stopPropagation(); close(); }
    }}>
        <div className={styles.heading}><strong>{label}品名与件数</strong><span>品名</span><span>件数</span></div>
        <div className={styles.items}>
            {details.map((row, index) => <div className={styles.item} key={index}>
                <AutoComplete ref={index === 0 ? firstNameRef : undefined} className={styles.name} value={row.item_name} options={options} disabled={disabled}
                    filterOption={(input, option) => String(option?.value || '').toLocaleLowerCase().includes(input.toLocaleLowerCase())}
                    onChange={value => updateItem(index, 'item_name', value)}>
                    <Input aria-label={details.length === 1 ? `${label}品名` : `${label}第${index + 1}项品名`} placeholder="选择品名或输入" />
                </AutoComplete>
                <InputNumber aria-label={details.length === 1 ? `${label}件数` : `${label}第${index + 1}项件数`}
                    className={styles.quantity} value={row.piece_count} placeholder="件数" min={1} max={MAX_INTAKE_PIECE_COUNT}
                    precision={0} disabled={disabled} onChange={value => updateItem(index, 'piece_count', value)} />
                <Button type="text" danger icon={<DeleteOutlined />} aria-label={`删除${label}第${index + 1}项品名`}
                    disabled={disabled || details.length <= 1} onClick={() => { if (!disabled) onChange(details.filter((_, i) => i !== index)); }} />
            </div>)}
        </div>
        <div className={styles.actions}>
            <Button type="link" size="small" icon={<PlusOutlined />} disabled={disabled || details.length >= MAX_INTAKE_ITEMS}
                aria-label={`${label}添加品名`} onClick={() => { if (!disabled && details.length < MAX_INTAKE_ITEMS) onChange([...details, emptyIntakeItemDetail()]); }}>添加品名</Button>
            <Button size="small" onClick={close}>完成</Button>
        </div>
    </section>;

    return <Popover trigger="click" placement="bottomLeft" arrow={false} autoAdjustOverflow={{ adjustX: true, adjustY: true, shiftX: true }} open={open && !disabled}
        onOpenChange={nextOpen => setOpen(!disabled && nextOpen)} afterOpenChange={visible => { if (visible && !disabled) firstNameRef.current?.focus(); }} content={content} destroyOnHidden>
        <Input ref={summaryRef} className={styles.summary} aria-label={`${label}品名与件数`} value={summary} readOnly
            aria-haspopup="dialog" aria-expanded={open && !disabled} aria-controls={open ? dialogId : undefined}
            disabled={disabled} placeholder="点击填写品名和数量" title={summary || undefined}
            suffix={<DownOutlined className={open ? styles.expanded : ''} />} onKeyDown={event => {
                if (disabled) return;
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(current => !current); }
                if (event.key === 'Escape') close();
            }} />
    </Popover>;
}
