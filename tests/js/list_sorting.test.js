const test = require('node:test');
const assert = require('node:assert/strict');

const { compareSortValues, sortRows } = require('../../static/js/list_sorting.js');

function row(value, originalIndex, text = value) {
  return {
    originalIndex,
    cells: [{ text, sortValue: value }],
  };
}

test('sorts numeric sort values numerically in either direction', () => {
  const rows = [row('20', 0), row('3', 1), row('100', 2)];

  assert.deepEqual(sortRows(rows, 0, 'ascending', 'en').map((item) => item.cells[0].sortValue), ['3', '20', '100']);
  assert.deepEqual(sortRows(rows, 0, 'descending', 'en').map((item) => item.cells[0].sortValue), ['100', '20', '3']);
});

test('uses natural, language-aware comparison for text including CJK', () => {
  const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });

  assert.ok(compareSortValues('元件 2', '元件 10', collator) < 0);
  assert.ok(compareSortValues('电容', '电阻', collator) !== 0);
  assert.ok(compareSortValues('$0.11', '$0.2', collator) < 0);
  assert.ok(compareSortValues('C2', 'C10', collator) < 0);
});

test('keeps empty cells at the end in both directions', () => {
  const rows = [row('', 0), row('Alpha', 1), row('0', 2, '0'), row('-', 3, '-')];

  assert.deepEqual(sortRows(rows, 0, 'ascending', 'en').map((item) => item.originalIndex), [2, 1, 0, 3]);
  assert.deepEqual(sortRows(rows, 0, 'descending', 'en').map((item) => item.originalIndex), [1, 2, 0, 3]);
});

test('preserves source order for equal keys', () => {
  const rows = [row('same', 0), row('same', 1), row('same', 2)];

  assert.deepEqual(sortRows(rows, 0, 'ascending', 'en').map((item) => item.originalIndex), [0, 1, 2]);
  assert.deepEqual(sortRows(rows, 0, 'descending', 'en').map((item) => item.originalIndex), [0, 1, 2]);
});
