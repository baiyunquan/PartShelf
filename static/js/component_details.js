const I18N = JSON.parse(document.getElementById('page-translations').textContent);
const urlParams = new URLSearchParams(window.location.search);
const partId = urlParams.get("part_id");
    
if (!partId) {
  alert(I18N.missing_part_id);
  window.location.href = "/inventory";
}

fetch(`/api/inventory/get_part_by_id?part_id=${partId}`)
  .then(res => {
    if (!res.ok) throw new Error(I18N.alert_fetch_failed);
    return res.json();
  })
  .then(data => {
    document.getElementById("part-id").textContent = `#${data.id}`;
    document.getElementById("part-name").textContent = data.name || '-';
    document.getElementById("part-manufacturer").textContent = data.manufacturer || '-';
    document.getElementById("part-type").textContent = data.part_type || '-';
    document.getElementById("part-package").textContent = data.package || '-';
    document.getElementById("part-quantity").textContent = (data.quantity !== null && data.quantity !== undefined) ? data.quantity : 0;
    document.getElementById("part-description").textContent = data.description || I18N.no_description;
    
    const quantity = data.quantity || 0;
    const inStockSpan = document.getElementById('in-stock-status');
    if (quantity > 0) {
      inStockSpan.textContent = I18N.status_in_stock;
      inStockSpan.className = 'badge bg-success';
    } else {
      inStockSpan.textContent = I18N.status_out_of_stock;
      inStockSpan.className = 'badge bg-danger';
    }
  })
  .catch(error => {
    console.error(I18N.alert_fetch_failed, error);
    alert(I18N.alert_fetch_failed);
  });

function updateQuantity() {
  const inputVal = document.getElementById('updateQuantity').value.trim();
  const delta = parseInt(inputVal, 10);
  if (isNaN(delta) || delta === 0) {
    alert(I18N.alert_invalid_quantity);
    return;
  }

  fetch('/api/inventory/update_quantity', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      part_id: parseInt(partId),
      quantity: delta
    })
  })
  .then(response => {
    if (!response.ok) {
      return response.json().then(err => { throw new Error(err.detail || I18N.alert_update_failed); });
    }
    return response.json();
  })
  .then(data => {
    location.reload(); 
  })
  .catch(error => {
    console.error('Error:', error);
    alert(error.message || I18N.alert_update_failed);
  });
}

function deletePart() {
  if (!window.confirm(I18N.confirm_delete)) return; 

  fetch(`/api/inventory/delete_part?part_id=${partId}`, {
    method: 'DELETE'
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(I18N.alert_delete_failed);
    }
    return response.json();
  })
  .then(() => {
    window.location.href = "/inventory";
  })
  .catch(error => {
    console.error('Error:', error);
    alert(I18N.alert_delete_failed);
  });
}

document.getElementById('updateQuantityBtn').addEventListener('click', updateQuantity);
document.getElementById('deletePartBtn').addEventListener('click', deletePart);
document.getElementById('viewHistoryBtn').addEventListener('click', () => alert(I18N.history_coming_soon));
document.getElementById('exportDetailsBtn').addEventListener('click', () => alert(I18N.export_coming_soon));
