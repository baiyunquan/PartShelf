(function (root, factory) {
  const sorting = factory();

  if (typeof module === 'object' && module.exports) {
    module.exports = sorting;
  }

  if (root && root.document) {
    sorting.install(root.document);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const EMPTY_VALUES = new Set(['', '-', '—', '–', 'n/a', 'na', 'null', 'undefined']);
  const NUMBER_PATTERN = /^[+-]?(?:\d+\.?\d*|\.\d+)$/;
  const NUMERIC_PREFIX_PATTERN = /^(?:#|c|[$€£¥￥])([+-]?(?:\d+\.?\d*|\.\d+))$/i;

  function normalizedValue(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/\s+/g, ' ').trim();
  }

  function isEmptyValue(value) {
    return EMPTY_VALUES.has(normalizedValue(value).toLocaleLowerCase());
  }

  function parseNumericValue(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;

    const text = normalizedValue(value).replace(/[\s,，]/g, '');
    if (NUMBER_PATTERN.test(text)) return Number(text);

    const prefixed = text.match(NUMERIC_PREFIX_PATTERN);
    return prefixed ? Number(prefixed[1]) : null;
  }

  function compareSortValues(left, right, collator) {
    const leftText = normalizedValue(left);
    const rightText = normalizedValue(right);
    const leftEmpty = isEmptyValue(leftText);
    const rightEmpty = isEmptyValue(rightText);

    if (leftEmpty || rightEmpty) {
      if (leftEmpty === rightEmpty) return 0;
      return leftEmpty ? 1 : -1;
    }

    const leftNumber = parseNumericValue(leftText);
    const rightNumber = parseNumericValue(rightText);
    if (leftNumber !== null && rightNumber !== null) {
      return leftNumber === rightNumber ? 0 : leftNumber < rightNumber ? -1 : 1;
    }

    return collator.compare(leftText, rightText);
  }

  function cellValue(cell) {
    if (!cell) return '';
    if (Object.prototype.hasOwnProperty.call(cell, 'sortValue') && cell.sortValue !== null && cell.sortValue !== undefined) {
      return cell.sortValue;
    }
    return cell.text || '';
  }

  function sortRows(rows, columnIndex, direction, locale) {
    const collator = new Intl.Collator(locale || undefined, {
      numeric: true,
      sensitivity: 'base',
      ignorePunctuation: false,
    });
    const factor = direction === 'descending' ? -1 : 1;

    return rows.map((row, index) => ({
      row,
      sourceIndex: Number.isInteger(row.originalIndex) ? row.originalIndex : index,
    })).sort((left, right) => {
      const leftValue = cellValue(left.row.cells[columnIndex]);
      const rightValue = cellValue(right.row.cells[columnIndex]);
      const leftEmpty = isEmptyValue(leftValue);
      const rightEmpty = isEmptyValue(rightValue);

      if (leftEmpty !== rightEmpty) return leftEmpty ? 1 : -1;

      const result = compareSortValues(leftValue, rightValue, collator);
      if (result !== 0) return result * factor;
      return left.sourceIndex - right.sourceIndex;
    }).map((entry) => entry.row);
  }

  function isSortableHeader(header) {
    if (header.dataset.sortable === 'false') return false;
    return !header.querySelector('input, button, select, img');
  }

  function setHeaderState(table, activeHeader, direction) {
    table.querySelectorAll('thead th').forEach((header) => {
      if (header.dataset.listSortable !== 'true') return;
      if (header === activeHeader) {
        header.setAttribute('aria-sort', direction);
      } else {
        header.setAttribute('aria-sort', 'none');
      }
    });
  }

  function decorateTable(table) {
    table.querySelectorAll('thead th').forEach((header) => {
      if (!isSortableHeader(header)) {
        header.dataset.listSortable = 'false';
        header.removeAttribute('tabindex');
        header.removeAttribute('aria-sort');
        return;
      }

      header.dataset.listSortable = 'true';
      header.tabIndex = 0;
      if (!header.hasAttribute('aria-sort')) header.setAttribute('aria-sort', 'none');
    });
  }

  function resetTable(table) {
    delete table.dataset.listSortColumn;
    delete table.dataset.listSortDirection;
    table.querySelectorAll('thead th[data-list-sortable="true"]').forEach((header) => {
      header.setAttribute('aria-sort', 'none');
    });
  }

  function readRows(tbody) {
    return Array.from(tbody.rows).map((element, originalIndex) => ({
      element,
      originalIndex,
      cells: Array.from(element.cells).map((cell) => ({
        text: normalizedValue(cell.textContent),
        sortValue: cell.querySelector('input[type="number"], select, textarea')?.value
          ?? (cell.hasAttribute('data-sort-value') ? cell.dataset.sortValue : undefined),
      })),
    }));
  }

  function applySort(table, header) {
    const headers = Array.from(header.parentElement.children);
    const columnIndex = headers.indexOf(header);
    const tbody = table.tBodies[0];
    if (columnIndex < 0 || !tbody) return;

    const rows = readRows(tbody).filter((row) => row.cells.length > columnIndex);
    if (rows.length < 2) return;

    const sameColumn = table.dataset.listSortColumn === String(columnIndex);
    const direction = sameColumn && table.dataset.listSortDirection === 'ascending'
      ? 'descending'
      : 'ascending';
    const sorted = sortRows(rows, columnIndex, direction, table.ownerDocument.documentElement.lang);

    sorted.forEach((row) => tbody.appendChild(row.element));
    table.dataset.listSortColumn = String(columnIndex);
    table.dataset.listSortDirection = direction;
    setHeaderState(table, header, direction);
  }

  function mutationTables(records) {
    const tables = new Map();
    records.forEach((record) => {
      const targetTable = record.target.closest && record.target.closest('table[data-list-layout]');
      if (targetTable) {
        if (!tables.has(targetTable)) tables.set(targetTable, []);
        tables.get(targetTable).push(record);
      }

      record.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.matches && node.matches('table[data-list-layout]')) {
          if (!tables.has(node)) tables.set(node, []);
        }
        node.querySelectorAll?.('table[data-list-layout]').forEach((table) => {
          if (!tables.has(table)) tables.set(table, []);
        });
      });
    });
    return tables;
  }

  function isRowReorder(records) {
    const rowRecords = records.filter((record) => record.type === 'childList' && record.target.tagName === 'TBODY');
    if (rowRecords.length === 0 || rowRecords.length !== records.length) return false;

    const removed = new Map();
    const added = new Map();
    rowRecords.forEach((record) => {
      record.removedNodes.forEach((node) => {
        if (node.nodeType === 1 && node.tagName === 'TR') removed.set(node, (removed.get(node) || 0) + 1);
      });
      record.addedNodes.forEach((node) => {
        if (node.nodeType === 1 && node.tagName === 'TR') added.set(node, (added.get(node) || 0) + 1);
      });
    });

    if (removed.size === 0 || removed.size !== added.size) return false;
    return Array.from(removed).every(([row, count]) => added.get(row) === count);
  }

  function install(document) {
    if (!document.body || document.body.dataset.listSortingInstalled === 'true') return;
    document.body.dataset.listSortingInstalled = 'true';

    const tables = () => document.querySelectorAll('table[data-list-layout]');
    tables().forEach(decorateTable);

    document.addEventListener('click', (event) => {
      const header = event.target.closest && event.target.closest('th[data-list-sortable="true"]');
      if (!header || !isSortableHeader(header)) return;
      const table = header.closest('table[data-list-layout]');
      if (!table) return;
      applySort(table, header);
    });

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const header = event.target.closest && event.target.closest('th[data-list-sortable="true"]');
      if (!header || !isSortableHeader(header)) return;
      const table = header.closest('table[data-list-layout]');
      if (!table) return;
      event.preventDefault();
      applySort(table, header);
    });

    if (typeof MutationObserver === 'undefined') return;
    const observer = new MutationObserver((records) => {
      mutationTables(records).forEach((changes, table) => {
        decorateTable(table);
        if (!isRowReorder(changes)) resetTable(table);
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  return { compareSortValues, sortRows, install };
});
