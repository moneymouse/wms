const displayValue = value => value === false ? '转单号未填' : String(value ?? '').trim() || '未填写';

function describeFailure(item) {
    return `订单号: ${displayValue(item.order_id || item.order_uid)}；原单号: ${displayValue(item.transfer_id)}；转单号: ${displayValue(item.waybill_id)}；失败原因: ${item.reason || '上传失败'}`;
}

export function getWaybillUploadResult(responseBody = {}, filename = '文件') {
    const body = responseBody && typeof responseBody === 'object' ? responseBody : {};
    const hasSuccessItems = Array.isArray(body.success_items);
    const successList = Array.isArray(body.success_list) ? body.success_list : [];
    const savedCount = hasSuccessItems ? body.success_items.length
        : Number(body.cargo_count ?? successList.length) || 0;
    const trackingFailed = Boolean(body.tracking_error) || body.code === 502
        || (body.code === 500 && (savedCount > 0 || body.msg === 'Register Error'));
    let failures;
    if (Array.isArray(body.failed_list)) {
        // The server identifies failed records; waybill numbers are not unique.
        failures = body.failed_list;
    } else {
        // Compatibility with servers that only returned the original number map.
        const successfulWaybills = new Set(successList.map(item => String(item[1])));
        failures = Object.entries(body.cargo_list || {})
            .filter(([, waybill]) => !successfulWaybills.has(String(waybill)))
            .map(([transfer_id, waybill_id]) => ({
                transfer_id, waybill_id,
                reason: trackingFailed || body.code === 200
                    ? '未匹配货物或未保存' : body.msg || '上传失败',
            }));
    }

    const rejected = Array.isArray(body.rejected)
        ? body.rejected.map(item => item?.number || item) : [];
    const saveRequestFailed = ![200, 207].includes(body.code) && !trackingFailed;
    const hasFailures = failures.length > 0;
    const reportLines = [
        `上传成功记录数: ${savedCount}条`,
        `上传失败记录数: ${failures.length}条`,
        ...(body.code === 207 ? [`上传结果: ${body.msg || '部分订单上传失败，其他订单已保存'}`] : []),
        ...(saveRequestFailed ? [`失败原因: ${body.msg || '上传失败'}`] : []),
        '上传失败记录:',
        ...(hasFailures ? failures.map(describeFailure) : ['无']),
        '',
        '追踪注册失败（已保存记录不会回滚）:',
        ...(trackingFailed ? [
            body.tracking_error?.reason || body.msg || '追踪注册失败',
            ...rejected.map(String),
        ] : ['无']),
    ];

    let toast;
    if (trackingFailed) {
        toast = {
            type: 'warning',
            message: `${filename}：已保存 ${savedCount} 条${hasFailures ? `，${failures.length} 条未保存` : ''}，追踪注册失败，请查看上传结果记录`,
        };
    } else if (body.code === 207 || (savedCount > 0 && hasFailures)) {
        toast = {
            type: 'warning',
            message: `${filename}：已保存 ${savedCount} 条，${failures.length} 条失败，请查看上传结果记录`,
        };
    } else if (saveRequestFailed || hasFailures) {
        toast = { type: 'error', message: body.msg || `${filename} 上传失败！` };
    } else {
        toast = { type: 'success', message: `${filename}：已保存 ${savedCount} 条` };
    }

    return {
        savedCount, failures, trackingFailed, reportLines, toast,
        status: saveRequestFailed || hasFailures || trackingFailed || body.code === 207 ? 'error' : 'done',
    };
}
