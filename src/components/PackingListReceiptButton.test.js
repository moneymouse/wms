import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import PackingListReceiptButton from './PackingListReceiptButton';

jest.mock('../pages/financeWorkspace', () => ({ PaymentEditor: function MockPaymentEditor({ initialContext, onClose }) {
    return <div role="dialog" aria-label="登记收付款"><span>{initialContext.referenceNote}</span>
        <span data-testid="reference-boxes">{initialContext.referenceBoxUids.join(',')}</span>
        <button onClick={onClose}>取消</button></div>;
} }));

const packingList = { uid: 'packing-1', list_number: 'MARK-1', customer_id: 42, customer_name: '客户甲',
    boxes: Array.from({ length: 501 }, (_, index) => ({ uid: `box-${index + 1}`, box_number: index + 1 })) };

test('a list above 500 boxes requests explicit selection and never silently truncates the defaults', () => {
    render(<PackingListReceiptButton packingList={packingList} />);
    fireEvent.click(screen.getByRole('button', { name: '登记收付款' }));
    const dialog = screen.getByRole('dialog', { name: '登记收付款' });
    expect(within(dialog).getByText(/当前装箱单有 501 箱，超过每笔 500 箱的备注上限/)).toBeInTheDocument();
    expect(within(dialog).getByTestId('reference-boxes')).toHaveTextContent('');
});

test('the selected-box snapshot remains stable until closing and reopening the registration', () => {
    const { rerender } = render(<PackingListReceiptButton packingList={packingList} selectedBoxUids={['box-501']} />);
    fireEvent.click(screen.getByRole('button', { name: '登记收付款' }));
    expect(screen.getByTestId('reference-boxes')).toHaveTextContent(/^box-501$/);
    rerender(<PackingListReceiptButton packingList={packingList} selectedBoxUids={['box-1']} />);
    expect(screen.getByTestId('reference-boxes')).toHaveTextContent(/^box-501$/);
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    fireEvent.click(screen.getByRole('button', { name: '登记收付款' }));
    expect(screen.getByTestId('reference-boxes')).toHaveTextContent(/^box-1$/);
});
