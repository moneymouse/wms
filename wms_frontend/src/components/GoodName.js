import { AutoComplete } from 'antd';
import React, { forwardRef, useEffect, useMemo, useState } from 'react';

import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';

export const fallbackGoodsNames = [
    'CLOTH', 'T-SHIRT', 'SWEATSHIRT', 'VEST', 'DRESS', 'SUIT', 'SCARF', 'SHORTS',
    'SHIRT', 'SWEATER', 'BLAZER', 'BAG', 'HAND BAG', 'PURSE', 'WALLET', 'BRIEFCASE',
    'SHOULDER BAG', 'HOLDALL', 'BACKPACK', 'BROOCH', 'CUFFINK', 'PENDANT', 'EARRING',
    'BUCKLE', 'LABEL',
];

const toOption = name => ({ label: name, value: name });

export function buildGoodsNameGroups(records) {
    const groups = new Map();
    (records || []).forEach(record => {
        const name = String(record?.name || '').trim();
        if (!name) return;
        const category = String(record?.category || '').trim() || '未分类';
        if (!groups.has(category)) groups.set(category, new Set());
        groups.get(category).add(name);
    });

    return Array.from(groups.entries())
        .sort(([categoryA], [categoryB]) => {
            if (categoryA === '未分类') return 1;
            if (categoryB === '未分类') return -1;
            return categoryA.localeCompare(categoryB, 'zh-CN');
        })
        .map(([category, names]) => ({
            label: category,
            options: Array.from(names)
                .sort((nameA, nameB) => nameA.localeCompare(nameB, 'en', { sensitivity: 'base' }))
                .map(toOption),
        }));
}

const fallbackGroups = [{ label: '常用品名', options: fallbackGoodsNames.map(toOption) }];

const GoodName = forwardRef(function GoodName(
    { onChange, onBlur, onEnter, defaultValue, style },
    ref,
) {
    const [groups, setGroups] = useState(fallbackGroups);
    const [searchValue, setSearchValue] = useState('');

    useEffect(() => {
        let active = true;
        const loadGoodsNames = async () => {
            try {
                const response = await fetch(`${endpoint}/goods-names?lang=en`, {
                    headers: getSafeHeader(),
                });
                const result = await response.json();
                const loadedGroups = result.code === 200 ? buildGoodsNameGroups(result.data) : [];
                if (active && loadedGroups.length > 0) setGroups(loadedGroups);
            } catch (error) {
                console.error('Fetch English goods names error:', error);
            }
        };
        loadGoodsNames();
        return () => {
            active = false;
        };
    }, []);

    const options = useMemo(() => {
        const keyword = searchValue.trim().toLocaleLowerCase();
        if (!keyword) return groups;
        return groups
            .map(group => ({
                ...group,
                options: group.options.filter(option => option.value.toLocaleLowerCase().includes(keyword)),
            }))
            .filter(group => group.options.length > 0);
    }, [groups, searchValue]);

    return (
        <AutoComplete
            ref={ref}
            defaultValue={defaultValue}
            options={options}
            filterOption={false}
            onSearch={setSearchValue}
            onSelect={onBlur}
            onBlur={onBlur}
            onKeyUp={event => event.code === 'Enter' && onEnter?.()}
            onChange={onChange}
            style={{ width: '100%', ...style }}
        />
    );
});

export default GoodName;
