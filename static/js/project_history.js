(function () {
  const i18n = JSON.parse(document.getElementById('page-translations').textContent || '{}');
  const rowsNode = document.getElementById('project-history-rows');
  const memberFilter = document.getElementById('history-member-filter');
  const summaryNode = document.getElementById('project-history-page-summary');
  const errorNode = document.getElementById('project-history-error');
  const previousButton = document.getElementById('project-history-previous');
  const nextButton = document.getElementById('project-history-next');
  const pageParams = new URLSearchParams(window.location.search);
  const pageSize = 50;
  const partId = pageParams.get('part_id');
  let page = Math.max(1, Number.parseInt(pageParams.get('page') || '1', 10) || 1);
  let pages = 0;

  function setTextCell(row, text, className) {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    cell.textContent = text || '';
    row.appendChild(cell);
    return cell;
  }

  function appendLinkedCell(row, label, href) {
    const cell = document.createElement('td');
    if (href) {
      const link = document.createElement('a');
      link.href = href;
      link.textContent = label || '';
      link.className = 'text-decoration-none';
      cell.appendChild(link);
    } else {
      cell.textContent = label || '';
    }
    row.appendChild(cell);
  }

  function selectedMember() {
    const option = memberFilter.selectedOptions[0];
    if (memberFilter.value === 'unattributed') return { unattributed: true };
    if (option && option.dataset.username !== undefined) {
      return { username: option.dataset.username };
    }
    return {};
  }

  function syncAddressBar() {
    const params = new URLSearchParams(window.location.search);
    params.delete('username');
    params.delete('unattributed');
    params.set('page', String(page));
    if (partId) params.set('part_id', partId);
    const selected = selectedMember();
    if (selected.username !== undefined) params.set('username', selected.username);
    if (selected.unattributed) params.set('unattributed', '1');
    window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`);
  }

  function populateMembers(members) {
    const current = selectedMember();
    memberFilter.querySelectorAll('option[data-username]').forEach(option => option.remove());
    members.forEach((username, index) => {
      const option = document.createElement('option');
      option.value = `member-${index}`;
      option.dataset.username = username;
      option.textContent = username;
      memberFilter.appendChild(option);
    });

    if (current.unattributed) {
      memberFilter.value = 'unattributed';
    } else if (current.username !== undefined) {
      const matching = Array.from(memberFilter.options).find(
        option => option.dataset.username === current.username
      );
      memberFilter.value = matching ? matching.value : 'all';
    }
  }

  function renderRows(items) {
    rowsNode.replaceChildren();
    if (!items.length) {
      const row = document.createElement('tr');
      const cell = setTextCell(row, i18n.no_records || 'No history records.');
      cell.colSpan = 6;
      cell.className = 'text-center text-muted py-4';
      rowsNode.appendChild(row);
      return;
    }

    const actionLabels = {
      added: i18n.action_added,
      quantity_changed: i18n.action_quantity_changed,
      removed: i18n.action_removed,
    };
    items.forEach(item => {
      const row = document.createElement('tr');
      const date = new Date(item.changed_at);
      setTextCell(row, Number.isNaN(date.getTime()) ? item.changed_at : date.toLocaleString(), 'history-time');
      setTextCell(row, item.username || i18n.no_operator || 'No operator');
      appendLinkedCell(
        row,
        item.project_name || `#${item.project_id || ''}`,
        item.project_exists ? `/project_details?project_id=${encodeURIComponent(item.project_id)}` : ''
      );
      const componentLabel = item.part_name || `${item.part_source || ''}:${item.part_external_id || ''}`;
      const componentCell = document.createElement('td');
      const labelNode = document.createElement(item.part_exists ? 'a' : 'span');
      if (item.part_exists) {
        labelNode.href = `/component_details?part_id=${encodeURIComponent(item.part_id)}`;
        labelNode.className = 'text-decoration-none';
      }
      labelNode.textContent = componentLabel;
      componentCell.appendChild(labelNode);
      const identity = `${item.part_source || ''}:${item.part_external_id || ''}`;
      if (identity !== ':' && identity !== componentLabel) {
        const identityNode = document.createElement('small');
        identityNode.className = 'd-block text-muted';
        identityNode.textContent = identity;
        componentCell.appendChild(identityNode);
      }
      row.appendChild(componentCell);
      setTextCell(row, actionLabels[item.action] || item.action);
      const before = item.quantity_before === null ? '—' : item.quantity_before;
      const after = item.quantity_after === null ? '—' : item.quantity_after;
      setTextCell(row, `${before} -> ${after}`, 'history-quantity');
      rowsNode.appendChild(row);
    });
  }

  async function loadHistory() {
    errorNode.classList.add('d-none');
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (partId) params.set('part_id', partId);
    const selected = selectedMember();
    if (selected.username !== undefined) params.set('username', selected.username);
    if (selected.unattributed) params.set('unattributed', 'true');

    try {
      const response = await fetch(`/api/projects/history?${params.toString()}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      pages = data.pages;
      populateMembers(data.members || []);
      renderRows(data.items || []);
      const pageCount = Math.max(pages, 1);
      summaryNode.textContent = (i18n.page_summary || 'Page {page} of {pages}; {total} records total')
        .replace('{page}', String(page))
        .replace('{pages}', String(pageCount))
        .replace('{total}', String(data.total));
      previousButton.disabled = page <= 1;
      nextButton.disabled = !pages || page >= pages;
    } catch (error) {
      rowsNode.replaceChildren();
      errorNode.textContent = i18n.load_error || 'Failed to load history.';
      errorNode.classList.remove('d-none');
      summaryNode.textContent = '';
      previousButton.disabled = true;
      nextButton.disabled = true;
    }
  }

  const initialUsername = pageParams.get('username');
  if (pageParams.get('unattributed') === '1' || pageParams.get('unattributed') === 'true') {
    memberFilter.value = 'unattributed';
  }
  if (initialUsername !== null) {
    memberFilter.dataset.initialUsername = initialUsername;
  }

  memberFilter.addEventListener('change', () => {
    page = 1;
    syncAddressBar();
    loadHistory();
  });
  previousButton.addEventListener('click', () => {
    if (page > 1) {
      page -= 1;
      syncAddressBar();
      loadHistory();
    }
  });
  nextButton.addEventListener('click', () => {
    if (page < pages) {
      page += 1;
      syncAddressBar();
      loadHistory();
    }
  });

  loadHistory().then(() => {
    if (memberFilter.dataset.initialUsername !== undefined) {
      const matching = Array.from(memberFilter.options).find(
        option => option.dataset.username === memberFilter.dataset.initialUsername
      );
      if (matching) {
        memberFilter.value = matching.value;
        page = 1;
        loadHistory();
      }
      delete memberFilter.dataset.initialUsername;
    }
  });
})();
