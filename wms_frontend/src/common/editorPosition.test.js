import { captureEditorPosition, restoreEditorPosition } from './editorPosition';

afterEach(() => { document.body.innerHTML = ''; jest.restoreAllMocks(); });

test('restores nested vertical and horizontal scrollers and focuses without scrolling', () => {
    document.body.innerHTML = '<div id="outer" style="overflow-y:auto"><div id="inner" style="overflow:auto"><button>Edit</button></div></div>';
    const outer = document.getElementById('outer');
    const inner = document.getElementById('inner');
    const button = document.querySelector('button');
    [outer, inner].forEach(element => {
        Object.defineProperties(element, {
            scrollHeight: { value: 3000 }, clientHeight: { value: 600 },
            scrollWidth: { value: 1500 }, clientWidth: { value: 700 },
        });
    });
    outer.scrollTop = 80; inner.scrollTop = 1370; inner.scrollLeft = 240;
    button.getBoundingClientRect = () => ({ top: 200 });
    const snapshot = captureEditorPosition(button);
    outer.scrollTop = 0; inner.scrollTop = 0; inner.scrollLeft = 0;
    const focus = jest.spyOn(button, 'focus');
    restoreEditorPosition(snapshot);
    expect(outer.scrollTop).toBe(80);
    expect(inner.scrollTop).toBe(1370);
    expect(inner.scrollLeft).toBe(240);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(button).toHaveFocus();
});

test('compensates height changes above the same editor and ignores detached targets', () => {
    document.body.innerHTML = '<div style="overflow-y:auto"><input /></div>';
    const input = document.querySelector('input');
    const scroller = input.parentElement;
    Object.defineProperties(scroller, { scrollHeight: { value: 4000 }, clientHeight: { value: 700 } });
    scroller.scrollTop = 1200;
    let heightDelta = 0;
    input.getBoundingClientRect = () => ({ top: 300 + heightDelta - (scroller.scrollTop - 1200) });
    const snapshot = captureEditorPosition(input);
    heightDelta = 64;
    restoreEditorPosition(snapshot);
    expect(scroller.scrollTop).toBe(1264);
    expect(input.getBoundingClientRect().top).toBe(300);
    scroller.remove();
    const focus = jest.spyOn(input, 'focus');
    restoreEditorPosition(snapshot);
    expect(focus).not.toHaveBeenCalled();
    expect(captureEditorPosition(input)).toBeNull();
});
