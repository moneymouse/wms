export function calculateBillingWeight(weight) {
    const numericWeight = Number(weight || 0);
    return Number.isFinite(numericWeight) ? Math.ceil(numericWeight) : 0;
}

export function calculateOrderBillingWeight(weights = []) {
    return weights.reduce((total, weight) => total + calculateBillingWeight(weight), 0);
}

export function calculateReceivable(weight, unitPrice, surcharge) {
    return (
        calculateBillingWeight(weight) * Number(unitPrice || 0)
        + Number(surcharge || 0)
    );
}
