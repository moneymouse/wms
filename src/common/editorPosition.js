// The app scrolls inside Layout/Content, and tables can have another scroller.
// Keep the real ancestors rather than assuming the document is the viewport.
export function captureEditorPosition(element) {
    if (!element?.isConnected) return null;
    const doc = element.ownerDocument;
    const viewport = doc.scrollingElement || doc.documentElement;
    const scrolls = [];
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (parent === viewport) continue;
        const style = doc.defaultView.getComputedStyle(parent);
        const vertical = /auto|scroll|overlay/.test(style.overflowY || style.overflow)
            && parent.scrollHeight > parent.clientHeight;
        const horizontal = /auto|scroll|overlay/.test(style.overflowX || style.overflow)
            && parent.scrollWidth > parent.clientWidth;
        if (vertical || horizontal || parent.scrollTop || parent.scrollLeft) {
            scrolls.push({ element: parent, top: parent.scrollTop, left: parent.scrollLeft, vertical });
        }
    }
    scrolls.push({ element: viewport, top: viewport.scrollTop, left: viewport.scrollLeft,
        vertical: viewport.scrollHeight > viewport.clientHeight });
    return { element, scrolls, anchorTop: element.getBoundingClientRect().top };
}

export function restoreEditorPosition(snapshot, focusElement = snapshot?.element) {
    if (!snapshot || !focusElement?.isConnected) return;
    if (!focusElement.disabled) focusElement.focus({ preventScroll: true });
    snapshot.scrolls.forEach(({ element, top, left }) => {
        if (element.isConnected) {
            element.scrollTop = top;
            element.scrollLeft = left;
        }
    });
    // An error banner or refreshed row can change the height above the editor.
    // Keep the edited control at the same viewport offset where possible.
    const delta = focusElement.getBoundingClientRect().top - snapshot.anchorTop;
    const scroller = snapshot.scrolls.find(({ element, vertical }) => vertical && element.isConnected);
    if (scroller && delta) scroller.element.scrollTop += delta;
}
