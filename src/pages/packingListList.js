import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    Table,
    Card,
    Input,
    Select,
    Button,
    Space,
    Tag,
    Typography,
    message,
    Grid,
    Checkbox,
    Modal,
    Tree
} from 'antd';
import {
    SearchOutlined,
    PrinterOutlined,
    ReloadOutlined,
    FileSearchOutlined
} from '@ant-design/icons';
import { endpoint } from '../config';
import getSafeHeader from '../common/safeHeader';
import { canReviewIntake, getIntakeRoles } from '../common/intakeApi';
import MyPackingLists from '../components/MyPackingLists';
import entryStyles from './packingListEntry.module.css';

const { Title, Text } = Typography;
const { Option } = Select;

const BOX_STATUS = {
    PENDING_ASSIGN: 'pending_assign',
    PENDING_OUTBOUND: 'pending_outbound',
    OUTBOUND: 'outbound'
};

const BOX_STATUS_META = {
    [BOX_STATUS.PENDING_ASSIGN]: { text: '待分配', color: 'gold', level: 0 },
    [BOX_STATUS.PENDING_OUTBOUND]: { text: '待出库', color: 'blue', level: 1 },
    [BOX_STATUS.OUTBOUND]: { text: '已出库', color: 'green', level: 2 }
};

const PACKING_DRAFT_META = { text: '草稿', color: 'default', level: -1 };

const STATUS_TEXT_TO_CODE = {
    '草稿': 'draft',
    '待分配': 'pending_assign',
    '待出库': 'pending_outbound',
    '已出库': 'outbound'
};

const getMarkText = (record) => record?.list_number || record?.mark || '-';

const normalizeBoxStatus = (box) => {
    const raw = String(box?.status ?? '').trim().toLowerCase();
    if (raw === '1' || raw === BOX_STATUS.OUTBOUND) {
        return BOX_STATUS.OUTBOUND;
    }

    const hasOrder = !!box?.target_order_uid;
    if (!hasOrder) {
        return BOX_STATUS.PENDING_ASSIGN;
    }
    return BOX_STATUS.PENDING_OUTBOUND;
};

const getBoxStatusMeta = (box) => {
    const code = normalizeBoxStatus(box);
    return BOX_STATUS_META[code] || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

const getPackingListStatusMeta = (record) => {
    if (record?.status === 'draft') {
        return PACKING_DRAFT_META;
    }

    const boxes = Array.isArray(record?.boxes) ? record.boxes : [];
    if (boxes.length === 0) return BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];

    const minLevel = boxes.reduce((min, box) => {
        const meta = getBoxStatusMeta(box);
        return Math.min(min, meta.level);
    }, Number.MAX_SAFE_INTEGER);

    const matched = Object.values(BOX_STATUS_META).find((meta) => meta.level === minLevel);
    return matched || BOX_STATUS_META[BOX_STATUS.PENDING_ASSIGN];
};

export default function PackingListList() {
    const roles = getIntakeRoles();
    const workerOnly = roles.some(role => ['worker', 'employee'].includes(role)) &&
        !roles.some(role => ['admin', 'store_manager', 'salesperson', 'clerk', 'finance'].includes(role));
    return workerOnly ? <MyPackingLists /> : <PackingListWorkspace />;
}

function PackingListWorkspace() {
    const [messageApi, contextHolder] = message.useMessage();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const screens = Grid.useBreakpoint();

    // 数据状态
    const [packingLists, setPackingLists] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);

    // 筛选状态
    const [page, setPage] = useState(parseInt(searchParams.get('page')) || 1);
    const [pageSize, setPageSize] = useState(parseInt(searchParams.get('pageSize')) || 20);
    const [search, setSearch] = useState(searchParams.get('search') || '');
    const [searchInput, setSearchInput] = useState(searchParams.get('search') || '');
    const [reloadTick, setReloadTick] = useState(0);
    const [batchPrintVisible, setBatchPrintVisible] = useState(false);
    const [checkedPrintKeys, setCheckedPrintKeys] = useState([]);
    const [batchPrintLoading, setBatchPrintLoading] = useState(false);
    const [batchPrintSearch, setBatchPrintSearch] = useState('');
    const [status, setStatus] = useState(() => {
        const urlStatus = searchParams.get('status');
        if (urlStatus) return urlStatus.split(',');
        return typeof window !== 'undefined' && window.innerWidth < 768 ? ['待出库'] : ['草稿'];
    });
    const [excludeStatus, setExcludeStatus] = useState(() => {
        const urlExclude = searchParams.get('excludeStatus');
        if (urlExclude !== null) return urlExclude === 'true';
        return typeof window !== 'undefined' && window.innerWidth < 768 ? false : true;
    });

    // 同步状态到 URL
    useEffect(() => {
        const params = new URLSearchParams();
        if (page !== 1) params.set('page', page);
        if (pageSize !== 20) params.set('pageSize', pageSize);
        if (search) params.set('search', search);
        if (status && status.length > 0) params.set('status', status.join(','));
        params.set('excludeStatus', excludeStatus);
        setSearchParams(params, { replace: true });
    }, [page, pageSize, search, status, excludeStatus, setSearchParams]);

    // 防抖同步输入到搜索状态
    useEffect(() => {
        const timer = setTimeout(() => {
            if (search !== searchInput) {
                setSearch(searchInput);
                setPage(1);
            }
        }, 500);
        return () => clearTimeout(timer);
    }, [searchInput, search]);

    useEffect(() => {
        fetchPackingLists();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, pageSize, search, status, excludeStatus, reloadTick]);

    const fetchPackingLists = async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({
                p: page,
                s: pageSize,
                ...(search && { q: search })
            });

            if (status && status.length > 0) {
                const mappedStatus = status
                    .map((s) => STATUS_TEXT_TO_CODE[s])
                    .filter(Boolean)
                    .join(',');
                if (mappedStatus) {
                    params.set('box_status', mappedStatus);
                    params.set('exclude_box_status', String(excludeStatus));
                }
            }

            const res = await fetch(`${endpoint}/packing-lists?${params}`, {
                headers: getSafeHeader()
            });
            const data = await res.json();

            if (data.code === 200) {
                setPackingLists(data.data.items || []);
                setTotal(data.data.total || 0);
            } else {
                messageApi.error(data.msg || '获取数据失败');
            }
        } catch (error) {
            messageApi.error('获取装箱单列表失败');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    const handleSearch = () => {
        if (search !== searchInput) {
            setSearch(searchInput);
        }
        setPage(1);
        setReloadTick((t) => t + 1);
    };

    const handleViewDetail = (uid) => {
        navigate(`/packing-lists/${uid}`);
    };

    const handleOpenBatchPrint = () => {
        setCheckedPrintKeys([]);
        setBatchPrintSearch('');
        setBatchPrintVisible(true);
    };

    const getBatchPrintTreeData = () => (filteredBatchPrintLists || [])
        .filter((record) => Array.isArray(record?.boxes) && record.boxes.length > 0)
        .map((record) => ({
            key: `pl:${record.uid}`,
            title: `${getMarkText(record)} (${record.boxes.length} 箱)`,
            children: (record.boxes || []).map((box, idx) => ({
                key: `bx:${record.uid}:${box.uid}`,
                title: `箱子 ${box.box_number || (idx + 1)}`
            }))
        }));

    const parseSelectedPrintTargets = () => {
        const selected = new Set(checkedPrintKeys);
        const targets = [];

        (filteredPackingLists || []).forEach((record) => {
            const boxes = Array.isArray(record?.boxes) ? record.boxes : [];
            if (boxes.length === 0 || !record?.uid) return;

            const listKey = `pl:${record.uid}`;
            const selectedBoxUids = selected.has(listKey)
                ? boxes.map((box) => box.uid).filter(Boolean)
                : boxes
                    .map((box) => box?.uid)
                    .filter((boxUid) => boxUid && selected.has(`bx:${record.uid}:${boxUid}`));

            if (selectedBoxUids.length > 0) {
                targets.push({ packingListUid: record.uid, boxUids: selectedBoxUids });
            }
        });

        return targets;
    };

    const printPackingListsPdf = async (targets) => {
        const selections = (Array.isArray(targets) ? targets : [])
            .map((target) => ({
                packing_list_uid: target?.packingListUid,
                box_uids: (Array.isArray(target?.boxUids) ? target.boxUids : []).filter(Boolean)
            }))
            .filter((target) => target.packing_list_uid && target.box_uids.length > 0);
        if (selections.length === 0) return;
        const previewWindow = window.open('', '_blank');
        if (!previewWindow) {
            throw new Error('浏览器拦截了新窗口，请允许弹窗后重试');
        }
        previewWindow.document.write('正在生成装箱单 PDF...');
        const headers = { ...getSafeHeader(), 'Content-Type': 'application/json' };

        const res = await fetch(`${endpoint}/packing-lists/pdf`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ selections })
        });

        if (!res.ok) {
            previewWindow.close();
            let errMsg = '导出装箱单失败';
            const contentType = (res.headers.get('content-type') || '').toLowerCase();
            if (contentType.includes('application/json')) {
                const errData = await res.json();
                errMsg = errData?.msg || errMsg;
            }
            throw new Error(errMsg);
        }

        const blob = await res.blob();
        const blobUrl = window.URL.createObjectURL(blob);
        previewWindow.location.href = blobUrl;
        window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60 * 1000);
    };

    const handleBatchPrint = async () => {
        const targets = parseSelectedPrintTargets();
        if (targets.length === 0) {
            messageApi.warning('请至少选择一个装箱单中的箱子');
            return;
        }

        setBatchPrintLoading(true);
        try {
            await printPackingListsPdf(targets);
            const totalBoxCount = targets.reduce((sum, t) => sum + t.boxUids.length, 0);
            messageApi.success(`已导出 ${totalBoxCount} 个箱子的合并装箱单 PDF`);
            setBatchPrintVisible(false);
        } catch (error) {
            messageApi.error(error?.message || '批量打印失败');
            console.error(error);
        } finally {
            setBatchPrintLoading(false);
        }
    };

    const filteredPackingLists = packingLists || [];
    const batchPrintKeyword = batchPrintSearch.trim().toLowerCase();
    const filteredBatchPrintLists = batchPrintKeyword
        ? filteredPackingLists.filter((record) => {
            const mark = String(getMarkText(record) || '').toLowerCase();
            const customerName = String(record?.customer_name || '').toLowerCase();
            return mark.includes(batchPrintKeyword) || customerName.includes(batchPrintKeyword);
        })
        : filteredPackingLists;

    const columns = [
        {
            title: '唛头',
            key: 'mark',
            width: 180,
            render: (_, record) => (
                <Button
                    type="link"
                    onClick={() => handleViewDetail(record.uid)}
                    style={{ padding: 0, fontWeight: 'bold' }}
                >
                    {getMarkText(record)}
                </Button>
            )
        },
        {
            title: '客户名',
            dataIndex: 'customer_name',
            key: 'customer_name',
            width: 150
        },
        {
            title: '箱子数',
            dataIndex: 'boxes',
            key: 'box_count',
            width: 100,
            render: (boxes) => boxes?.length || 0
        },
        {
            title: '总重量',
            dataIndex: 'boxes',
            key: 'total_weight',
            width: 120,
            render: (boxes) => {
                const total = (boxes || []).reduce((sum, b) => sum + (b.weight || 0), 0);
                return `${total.toFixed(2)} kg`;
            }
        },
        {
            title: '状态',
            key: 'status',
            width: 100,
            render: (_, record) => {
                const s = getPackingListStatusMeta(record);
                return <Tag color={s.color}>{s.text}</Tag>;
            }
        },
        {
            title: '创建人',
            dataIndex: 'creator_name',
            key: 'creator_name',
            width: 100,
            responsive: ['md']
        },
        {
            title: '创建时间',
            dataIndex: 'create_date',
            key: 'create_date',
            width: 160,
            responsive: ['md']
        }
    ];

    return (
        <div style={{ padding: screens.md ? '24px' : '12px' }}>
            {contextHolder}

            <div className={entryStyles.listHeading}>
                <Title level={screens.md ? 2 : 4} style={{ margin: 0 }}>装箱单列表</Title>
                {canReviewIntake() && <Button type="link" icon={<FileSearchOutlined />} onClick={() => navigate('/intakes')}>待核对纸质单?</Button>}
            </div>

            {/* 搜索筛选 */}
            <Card style={{ marginBottom: 16 }} bodyStyle={screens.md ? {} : { padding: 12 }}>
                <Space wrap style={{ width: '100%' }}>
                    <Input
                        placeholder="搜索唛头或客户名"
                        prefix={<SearchOutlined />}
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        // onPressEnter={handleSearch}
                        style={{ width: 250 }}
                    />
                    <Select
                        mode="multiple"
                        placeholder="状态"
                        allowClear
                        value={status}
                        onChange={setStatus}
                        maxTagCount={3}
                        style={{ minWidth: 150, maxWidth: 250 }}
                    >
                        <Option value="草稿">草稿</Option>
                        <Option value="待分配">待分配</Option>
                        <Option value="待出库">待出库</Option>
                        <Option value="已出库">已出库</Option>
                    </Select>
                    <Checkbox
                        checked={excludeStatus}
                        onChange={(e) => setExcludeStatus(e.target.checked)}
                    >
                        排除所选状态
                    </Checkbox>
                    <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                        搜索
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={() => {
                        setSearchInput('');
                        setSearch('');
                        setStatus(window.innerWidth < 768 ? ['待出库'] : ['待分配']);
                        setExcludeStatus(false);
                        setPage(1);
                        setReloadTick((t) => t + 1);
                    }}>
                        重置
                    </Button>
                    <Button icon={<PrinterOutlined />} onClick={handleOpenBatchPrint}>
                        批量打印
                    </Button>
                </Space>
            </Card>

            {/* 数据表格 */}
            <Card bodyStyle={screens.md ? {} : { padding: 0 }}>
                <Table
                    dataSource={filteredPackingLists}
                    columns={columns}
                    rowKey="uid"
                    loading={loading}
                    scroll={{ x: 800 }}
                    pagination={{
                        current: page,
                        pageSize: pageSize,
                        total: total,
                        showSizeChanger: true,
                        showQuickJumper: true,
                        showTotal: (total) => `共 ${total} 条`,
                        onChange: (p, ps) => {
                            setPage(p);
                            setPageSize(ps);
                        }
                    }}
                />
            </Card>

            <Modal
                title="批量打印装箱单"
                open={batchPrintVisible}
                onCancel={() => setBatchPrintVisible(false)}
                onOk={handleBatchPrint}
                okText="打印"
                cancelText="取消"
                confirmLoading={batchPrintLoading}
                width={640}
            >
                <Text type="secondary">
                    请选择要打印的装箱单和箱子（选择装箱单即默认选择该单全部箱子）。
                </Text>
                <Input
                    placeholder="搜索唛头或客户名"
                    prefix={<SearchOutlined />}
                    value={batchPrintSearch}
                    onChange={(e) => setBatchPrintSearch(e.target.value)}
                    allowClear
                    style={{ marginTop: 12 }}
                />
                <div style={{ marginTop: 12, maxHeight: 420, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
                    <Tree
                        checkable
                        selectable={false}
                        checkedKeys={checkedPrintKeys}
                        onCheck={(keys) => setCheckedPrintKeys(Array.isArray(keys) ? keys : keys.checked)}
                        treeData={getBatchPrintTreeData()}
                    />
                </div>
            </Modal>
        </div>
    );
}
