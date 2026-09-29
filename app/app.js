let currentStatus = 'new';
let currentPage = 1;

document.addEventListener('DOMContentLoaded', () => {
    loadOffers(currentStatus);

    document.getElementById('selectAll').addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('.offer-check');
        checkboxes.forEach(cb => cb.checked = e.target.checked);
        updateSelectedCount();
    });
});

async function loadOffers(status, page = 1) {
    currentStatus = status;
    currentPage = page;

    // Update UI Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('border-blue-600', 'text-blue-600');
        btn.classList.add('text-gray-500');
        if (btn.dataset.status === status) {
            btn.classList.add('border-blue-600', 'text-blue-600');
            btn.classList.remove('text-gray-500');
        }
    });

    const response = await fetch(`/api/offers?status=${status}&page=${page}`);
    const data = await response.json();
    renderOffers(data.offers);
    renderPagination(data.total, data.size, data.page);
}

function renderOffers(offers) {
    const container = document.getElementById('offersBody');
    container.innerHTML = offers.map(offer => `
        <tr>
            <td class="px-6 py-4 whitespace-nowrap">
                <input type="checkbox" value="${offer.id}" class="offer-check rounded text-blue-600" onchange="updateSelectedCount()">
            </td>
            <td class="px-6 py-4">
                <div class="text-sm font-medium text-blue-600">
                    <a href="${offer.url}" target="_blank" class="hover:underline">${offer.title}</a>
                </div>
            </td>
            <td class="px-6 py-4 text-sm text-gray-500">${offer.company_name || 'N/A'}</td>
            <td class="px-6 py-4 text-sm text-gray-500">${offer.source_name || 'N/A'}</td>
            <td class="px-6 py-4 text-sm text-gray-500">${offer.location}</td>
            <td class="px-6 py-4 text-sm">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${getScoreClass(offer.score)}">
                    ${offer.score}%
                </span>
            </td>
            <td class="px-6 py-4 text-sm text-gray-500">${new Date(offer.created_at).toLocaleDateString()}</td>
            <td class="px-6 py-4 text-right text-sm font-medium">
                <select onchange="updateStatus(${offer.id}, this.value)" class="text-xs border-gray-300 rounded">
                    <option value="">Status...</option>
                    <option value="new" ${status === 'new' ? 'selected' : ''}>Nowa</option>
                    <option value="cv_sent">Wysłano CV</option>
                    <option value="replied">Odpowiedź</option>
                    <option value="archived">Archiwum</option>
                </select>
            </td>
        </tr>
    `).join('');
}

function getScoreClass(score) {
    if (score >= 70) return 'bg-green-100 text-green-800';
    if (score >= 50) return 'bg-yellow-100 text-yellow-800';
    return 'bg-gray-100 text-gray-800';
}

async function updateStatus(id, status) {
    if (!status) return;
    await fetch(`/api/offers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
    });
    loadOffers(currentStatus, currentPage);
}

async function applyBulkStatus() {
    const status = document.getElementById('bulkStatus').value;
    if (!status) return;

    const ids = Array.from(document.querySelectorAll('.offer-check:checked')).map(cb => parseInt(cb.value));
    if (ids.length === 0) return;

    await fetch('/api/offers/bulk/status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offer_ids: ids, status })
    });
    
    document.getElementById('selectAll').checked = false;
    loadOffers(currentStatus, currentPage);
}

function renderPagination(total, size, page) {
    const pages = Math.ceil(total / size);
    const container = document.getElementById('pagination');
    if (pages <= 1) { container.innerHTML = ''; return; }

    let html = '';
    for (let i = 1; i <= pages; i++) {
        html += `
            <button onclick="loadOffers('${currentStatus}', ${i})" 
                class="px-3 py-1 border rounded ${i === page ? 'bg-blue-600 text-white' : 'bg-white hover:bg-gray-100'}">
                ${i}
            </button>
        `;
    }
    container.innerHTML = html;
}
