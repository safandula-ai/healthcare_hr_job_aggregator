let currentStatus = 'new';
let currentPage = 1;
let currentSort = 'date_desc';
let currentFilters = {
    minScore: '',
    maxScore: '',
    source: '',
    company: ''
};
let scrapeStatusTimer = null;
let scrapeUiTimer = null;
let scrapeWasRunning = false;
let latestScrapeStatus = {};

document.addEventListener('DOMContentLoaded', () => {
    const offersBody = document.getElementById('offersBody');
    if (offersBody) {
        loadOfferFilterOptions();
        loadOffers(currentStatus);
    }
    pollScrapeStatus();

    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', (e) => {
            const checkboxes = document.querySelectorAll('.offer-check');
            checkboxes.forEach(cb => cb.checked = e.target.checked);
            updateSelectedCount();
        });
    }
});

async function loadOfferFilterOptions() {
    try {
        const response = await fetch('/api/offer-filter-options');
        if (!response.ok) return;
        const options = await response.json();
        populateFilterSelect('sourceFilter', options.sources || [], 'Wszystkie');
        populateFilterSelect('companyFilter', options.companies || [], 'Wszystkie');
    } catch (error) {
        console.error('Failed to load filter options:', error);
    }
}

function populateFilterSelect(id, values, emptyLabel) {
    const select = document.getElementById(id);
    if (!select) return;

    const previousValue = select.value;
    const uniqueValues = Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b, 'pl'));
    select.innerHTML = `<option value="">${emptyLabel}</option>` + uniqueValues
        .map(value => `<option value="${escapeAttribute(value)}">${escapeHtml(value)}</option>`)
        .join('');
    if (previousValue && uniqueValues.includes(previousValue)) {
        select.value = previousValue;
    }
}

async function loadOffers(status, page = 1) {
    const container = document.getElementById('offersBody');
    if (!container) return; // Exit if not on the dashboard

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

    readOfferControls();
    const response = await fetch(`/api/offers?${buildOffersQuery(status, page)}`);
    const data = await response.json();
    renderOfferCounts(data.total, data.status_counts || {});
    renderOffers(data.offers);
    renderPagination(data.total, data.size, data.page);
}

function renderOffers(offers) {
    const container = document.getElementById('offersBody');
    if (!container) return;

    if (!offers.length) {
        container.innerHTML = `
            <tr>
                <td colspan="8" class="px-6 py-10 text-center text-sm text-gray-500">
                    Brak ofert dla aktualnych filtrów.
                </td>
            </tr>
        `;
        resetSelectionState();
        return;
    }

    container.innerHTML = offers.map(offer => `
        <tr>
            <td class="px-6 py-4 whitespace-nowrap">
                <input type="checkbox" value="${offer.id}" class="offer-check rounded text-blue-600" onchange="updateSelectedCount()">
            </td>
            <td class="px-6 py-4 align-top">
                <div class="text-sm font-medium text-blue-600">
                    <a href="${offer.url}" target="_blank" class="hover:underline">${escapeHtml(offer.title)}</a>
                </div>
                ${formatOfferInfoPreview(offer.offer_info)}
                <div class="mt-2 flex flex-wrap gap-2">
                    <button type="button" onclick="toggleOfferDetails(${offer.id})" class="text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded hover:bg-blue-200">więcej</button>
                </div>
            </td>
            <td class="px-6 py-4 text-sm text-gray-500">${escapeHtml(offer.company_name || 'N/A')}</td>
            <td class="px-6 py-4 text-sm text-gray-500">${escapeHtml(offer.source_name || 'N/A')}</td>
            <td class="px-6 py-4 text-sm text-gray-500">${escapeHtml(offer.location || 'N/A')}</td>
            <td class="px-6 py-4 text-sm">
                <div>
                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${getScoreClass(offer.score)}">
                        ${offer.score}%
                    </span>
                </div>
            </td>
            <td class="px-6 py-4 text-sm text-gray-500">${new Date(offer.created_at).toLocaleDateString()}</td>
            <td class="px-6 py-4 text-right text-sm font-medium">
                <select onchange="updateStatus(${offer.id}, this.value, this)" data-current-status="${escapeAttribute(offer.status?.status || 'new')}" class="text-xs border-gray-300 rounded">
                    <option value="">Status...</option>
                    <option value="new" ${offer.status?.status === 'new' ? 'selected' : ''}>Nowa</option>
                    <option value="cv_sent" ${offer.status?.status === 'cv_sent' ? 'selected' : ''}>Wysłano CV</option>
                    <option value="replied" ${offer.status?.status === 'replied' ? 'selected' : ''}>Odpowiedź pracodawcy</option>
                    <option value="interview" ${offer.status?.status === 'interview' ? 'selected' : ''}>Rozmowa</option>
                    <option value="archived" ${offer.status?.status === 'archived' ? 'selected' : ''}>Archiwum</option>
                </select>
            </td>
        </tr>
        <tr id="details-${offer.id}" class="hidden bg-gray-50">
            <td colspan="8" class="px-6 py-4">
                <div id="details-content-${offer.id}" class="space-y-4"></div>
            </td>
        </tr>
    `).join('');
    resetSelectionState();
}

function resetSelectionState() {
    const selectAll = document.getElementById('selectAll');
    if (selectAll) selectAll.checked = false;
    updateSelectedCount();
}

async function toggleOfferDetails(id) {
    const detailsRow = document.getElementById(`details-${id}`);
    const detailsContent = document.getElementById(`details-content-${id}`);
    if (!detailsRow || !detailsContent) return;

    const isHidden = detailsRow.classList.contains('hidden');
    if (isHidden) {
        detailsRow.classList.remove('hidden');
        if (!detailsContent.dataset.loaded) {
            detailsContent.innerHTML = '<p class="text-sm text-gray-500">Ładowanie szczegółów...</p>';
            await loadOfferDetailsForAccordion(id);
        }
    } else {
        detailsRow.classList.add('hidden');
    }
}

async function loadOfferDetailsForAccordion(id) {
    const content = document.getElementById(`details-content-${id}`);
    if (!content) return;

    try {
        const response = await fetch(`/api/offers/${id}`);
        if (!response.ok) {
            content.innerHTML = '<p class="text-sm text-red-600">Nie udało się załadować szczegółów oferty.</p>';
            return;
        }
        const offer = await response.json();
        const interview = parseInterviewNotes(offer.status?.notes || '');

        content.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-gray-700">
                <div>
                    <p class="font-semibold text-gray-800">Firma</p>
                    <p>${escapeHtml(offer.company_name || 'N/A')}</p>
                </div>
                <div>
                    <p class="font-semibold text-gray-800">Źródło</p>
                    <p>${escapeHtml(offer.source_name || 'N/A')}</p>
                </div>
                <div>
                    <p class="font-semibold text-gray-800">Lokalizacja</p>
                    <p>${escapeHtml(offer.location || 'N/A')}</p>
                </div>
                <div>
                    <p class="font-semibold text-gray-800">Link do oferty</p>
                    <a href="${offer.url}" target="_blank" class="text-blue-600 hover:underline">Otwórz ofertę</a>
                </div>
                <div>
                    <p class="font-semibold text-gray-800">Status</p>
                    <p>${offer.status?.status || 'Brak'}</p>
                </div>
            </div>
            <div class="mt-4 bg-white border border-gray-200 rounded-lg p-4">
                <h3 class="font-semibold text-gray-800">Informacje z ogloszenia</h3>
                ${formatOfferInfo(offer.offer_info)}
            </div>
            <div class="mt-4 bg-white border border-gray-200 rounded-lg p-4">
                <h3 class="font-semibold text-gray-800">Dopasowanie</h3>
                <p class="text-sm text-gray-600 mt-2">Wynik: <strong>${offer.score}%</strong></p>
                ${formatMatchDetails(offer.match_details)}
            </div>
            <div class="mt-4 bg-white border border-gray-200 rounded-lg p-4">
                <h3 class="font-semibold text-gray-800">Rozmowa</h3>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2 text-sm text-gray-700">
                    <div>
                        <p class="font-medium">Data</p>
                        <p>${interview.date || 'Brak'}</p>
                    </div>
                    <div>
                        <p class="font-medium">Godzina</p>
                        <p>${interview.time || 'Brak'}</p>
                    </div>
                    <div>
                        <p class="font-medium">Lokalizacja</p>
                        <p>${interview.location || 'Brak'}</p>
                    </div>
                </div>
                ${formatOfferNotes(interview.notes)}
            </div>
        `;
        content.dataset.loaded = 'true';
    } catch (error) {
        content.innerHTML = '<p class="text-sm text-red-600">Błąd serwera podczas ładowania szczegółów.</p>';
    }
}

function readOfferControls() {
    currentSort = document.getElementById('sortFilter')?.value || currentSort;
    currentFilters = {
        minScore: document.getElementById('minScoreFilter')?.value || '',
        maxScore: document.getElementById('maxScoreFilter')?.value || '',
        source: document.getElementById('sourceFilter')?.value.trim() || '',
        company: document.getElementById('companyFilter')?.value.trim() || ''
    };
}

function buildOffersQuery(status, page) {
    const params = new URLSearchParams({
        status,
        page,
        sort: currentSort
    });
    if (currentFilters.minScore) params.set('min_score', currentFilters.minScore);
    if (currentFilters.maxScore) params.set('max_score', currentFilters.maxScore);
    if (currentFilters.source) params.set('source', currentFilters.source);
    if (currentFilters.company) params.set('company', currentFilters.company);
    return params.toString();
}

function applyOfferFilters() {
    loadOffers(currentStatus, 1);
}

function resetOfferFilters() {
    const fields = ['minScoreFilter', 'maxScoreFilter', 'sourceFilter', 'companyFilter'];
    fields.forEach(id => {
        const field = document.getElementById(id);
        if (field) field.value = '';
    });
    const sortFilter = document.getElementById('sortFilter');
    if (sortFilter) sortFilter.value = 'date_desc';
    currentSort = 'date_desc';
    currentFilters = { minScore: '', maxScore: '', source: '', company: '' };
    loadOffers(currentStatus, 1);
}

function setScoreSort() {
    currentSort = currentSort === 'score_desc' ? 'score_asc' : 'score_desc';
    const sortFilter = document.getElementById('sortFilter');
    if (sortFilter) sortFilter.value = currentSort;
    loadOffers(currentStatus, 1);
}

function renderOfferCounts(total, statusCounts) {
    const currentCount = document.getElementById('currentOffersCount');
    if (currentCount) {
        currentCount.textContent = total;
    }

    document.querySelectorAll('[data-count-status]').forEach(el => {
        const status = el.dataset.countStatus;
        el.textContent = statusCounts[status] ?? 0;
    });
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[char]));
}

function formatOfferInfoPreview(info) {
    if (!info) return '';
    const normalized = String(info).replace(/\s+/g, ' ').trim();
    const preview = normalized.length > 180 ? `${normalized.slice(0, 180)}...` : normalized;
    return `<p class="mt-2 text-xs text-gray-500 leading-5">${escapeHtml(preview)}</p>`;
}

function formatOfferInfo(info) {
    if (!info) {
        return '<p class="text-sm text-gray-600 mt-2">Brak dodatkowych informacji z ogloszenia.</p>';
    }
    return `<p class="text-sm text-gray-700 mt-2 whitespace-pre-line">${escapeHtml(info)}</p>`;
}

function formatMatchDetails(matchDetails = {}) {
    const positive = matchDetails.positive_matches || [];
    const negative = matchDetails.negative_reasons || [];
    let html = '';

    if (positive.length) {
        html += '<div class="mt-4">';
        html += '<p class="font-medium text-green-700">Szczegóły dopasowania</p>';
        html += '<ul class="list-disc list-inside text-sm text-gray-700 mt-2">';
        html += positive.map(item => `<li>${item}</li>`).join('');
        html += '</ul>';
        html += '</div>';
    }

    if (negative.length) {
        html += '<div class="mt-4">';
        html += '<p class="font-medium text-red-700">Potencjalne obszary do weryfikacji</p>';
        html += '<ul class="list-disc list-inside text-sm text-gray-700 mt-2">';
        html += negative.map(item => `<li>${item}</li>`).join('');
        html += '</ul>';
        html += '</div>';
    }

    if (!html) {
        html = '<p class="text-sm text-gray-600 mt-2">Brak szczegółowych informacji dopasowania.</p>';
    }

    return html;
}

function parseInterviewNotes(notes) {
    const data = { date: '', time: '', location: '', notes: '' };
    if (!notes) return data;

    const lines = notes.split('\n').map(line => line.trim());
    const remaining = [];

    lines.forEach(line => {
        if (line.startsWith('Rozmowa data:')) {
            data.date = line.replace('Rozmowa data:', '').trim();
        } else if (line.startsWith('Rozmowa godzina:')) {
            data.time = line.replace('Rozmowa godzina:', '').trim();
        } else if (line.startsWith('Rozmowa lokalizacja:')) {
            data.location = line.replace('Rozmowa lokalizacja:', '').trim();
        } else if (line.startsWith('Notatki rozmowy:')) {
            remaining.push(line.replace('Notatki rozmowy:', '').trim());
        } else {
            remaining.push(line);
        }
    });

    data.notes = remaining.join('\n').trim();
    return data;
}

function formatOfferNotes(notes) {
    if (!notes) {
        return '<p class="text-sm text-gray-600 mt-2">Brak dodatkowych notatek.</p>';
    }
    return `<div class="mt-4"><p class="font-medium">Notatki</p><p class="text-sm text-gray-700 mt-2 whitespace-pre-line">${notes}</p></div>`;
}

function getScoreClass(score) {
    if (score >= 70) return 'bg-green-100 text-green-800';
    if (score >= 50) return 'bg-yellow-100 text-yellow-800';
    return 'bg-gray-100 text-gray-800';
}

async function updateStatus(id, status, selectEl = null) {
    if (!status) return;
    if (status === 'interview') {
        await openInterviewModal(id, selectEl);
        return;
    }
    await fetch(`/api/offers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
    });
    loadOffers(currentStatus, currentPage);
}

async function openInterviewModal(id, selectEl = null) {
    const modal = document.getElementById('interviewModal');
    if (!modal) {
        await saveStatusWithNotes(id, 'interview', '');
        return;
    }

    modal.dataset.previousStatus = selectEl?.dataset.currentStatus || currentStatus || 'new';
    document.getElementById('interviewOfferId').value = id;
    document.getElementById('modalInterviewDate').value = '';
    document.getElementById('modalInterviewTime').value = '';
    document.getElementById('modalInterviewLocation').value = '';
    document.getElementById('modalInterviewNotes').value = '';

    try {
        const response = await fetch(`/api/offers/${id}`);
        if (response.ok) {
            const offer = await response.json();
            const interview = parseInterviewNotes(offer.status?.notes || '');
            document.getElementById('modalInterviewDate').value = interview.date || '';
            document.getElementById('modalInterviewTime').value = interview.time || '';
            document.getElementById('modalInterviewLocation').value = interview.location || '';
            document.getElementById('modalInterviewNotes').value = interview.notes || '';
        }
    } catch (error) {
        console.error('Failed to load interview notes:', error);
    }

    modal.classList.remove('hidden');
}

function closeInterviewModal() {
    const modal = document.getElementById('interviewModal');
    if (modal) modal.classList.add('hidden');
    loadOffers(currentStatus, currentPage);
}

function buildModalInterviewNotes() {
    const date = document.getElementById('modalInterviewDate')?.value || '';
    const time = document.getElementById('modalInterviewTime')?.value || '';
    const location = document.getElementById('modalInterviewLocation')?.value.trim() || '';
    const notes = document.getElementById('modalInterviewNotes')?.value.trim() || '';

    const lines = [];
    if (date) lines.push(`Rozmowa data: ${date}`);
    if (time) lines.push(`Rozmowa godzina: ${time}`);
    if (location) lines.push(`Rozmowa lokalizacja: ${location}`);
    if (notes) lines.push(`Notatki rozmowy: ${notes}`);
    return lines.join('\n');
}

async function saveInterviewStatus() {
    const id = document.getElementById('interviewOfferId')?.value;
    if (!id) return;
    await saveStatusWithNotes(id, 'interview', buildModalInterviewNotes());
    const modal = document.getElementById('interviewModal');
    if (modal) modal.classList.add('hidden');
    loadOffers('interview', 1);
}

async function saveStatusWithNotes(id, status, notes) {
    await fetch(`/api/offers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, notes })
    });
}

async function applyBulkStatus() {
    const status = document.getElementById('bulkStatus').value;
    if (!status) return;

    const ids = Array.from(document.querySelectorAll('.offer-check:checked')).map(cb => parseInt(cb.value));
    if (ids.length === 0) return;
    if (status === 'interview') {
        if (ids.length === 1) {
            await openInterviewModal(ids[0]);
        } else {
            alert('Dla statusu Rozmowa ustaw szczegóły osobno dla każdej oferty.');
        }
        return;
    }

    await fetch('/api/offers/bulk/status', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offer_ids: ids, status })
    });
    
    document.getElementById('selectAll').checked = false;
    loadOffers(currentStatus, currentPage);
}

function updateSelectedCount() {
    const count = document.querySelectorAll('.offer-check:checked').length;
    document.getElementById('selectedCount').innerText = `Zaznaczono: ${count}`;
}

async function triggerScrape() {
    setScrapeBusy(true);
    renderScrapeStatus({
        running: true,
        current_website: null,
        completed: 0,
        total: 0,
        last_error: null
    });
    
    try {
        const res = await fetch('/api/admin/scrape-now', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            renderScrapeStatus(data.status || {});
        } else {
            renderScrapeStatus({ running: false, last_error: 'Nie udało się uruchomić wyszukiwania.' });
        }
        startScrapeStatusPolling();
    } catch (error) {
        renderScrapeStatus({ running: false, last_error: 'Błąd połączenia podczas uruchamiania wyszukiwania.' });
        setScrapeBusy(false);
    }
}

function setScrapeBusy(isBusy) {
    const buttons = Array.from(document.querySelectorAll('#scrapeBtn, [data-scrape-button="true"]'));
    buttons.forEach(btn => {
        if (!btn.dataset.defaultText) {
            btn.dataset.defaultText = btn.innerText;
        }
        btn.disabled = isBusy;
        btn.innerText = isBusy ? 'Szukanie...' : btn.dataset.defaultText;
        btn.classList.toggle('bg-green-500', !isBusy);
        btn.classList.toggle('bg-green-600', !isBusy);
        btn.classList.toggle('hover:bg-green-600', !isBusy);
        btn.classList.toggle('hover:bg-green-700', !isBusy);
        btn.classList.toggle('bg-gray-400', isBusy);
        btn.classList.toggle('cursor-not-allowed', isBusy);
        btn.classList.toggle('opacity-80', isBusy);
    });
}

function startScrapeStatusPolling() {
    if (scrapeStatusTimer) return;
    scrapeStatusTimer = window.setInterval(pollScrapeStatus, 2000);
}

function stopScrapeStatusPolling() {
    if (!scrapeStatusTimer) return;
    window.clearInterval(scrapeStatusTimer);
    scrapeStatusTimer = null;
}

function startScrapeUiTicker() {
    if (scrapeUiTimer) return;
    scrapeUiTimer = window.setInterval(() => renderScrapeStatus(latestScrapeStatus), 1000);
}

function stopScrapeUiTicker() {
    if (!scrapeUiTimer) return;
    window.clearInterval(scrapeUiTimer);
    scrapeUiTimer = null;
}

async function pollScrapeStatus() {
    try {
        const response = await fetch('/api/admin/scrape-status');
        if (!response.ok) return;
        const status = await response.json();
        renderScrapeStatus(status);

        if (status.running) {
            scrapeWasRunning = true;
            startScrapeStatusPolling();
            return;
        }

        stopScrapeStatusPolling();
        if (scrapeWasRunning) {
            scrapeWasRunning = false;
            loadOfferFilterOptions();
            if (document.getElementById('offersBody')) {
                loadOffers(currentStatus, 1);
            }
        }
    } catch (error) {
        console.error('Failed to load scrape status:', error);
    }
}

function renderScrapeStatus(status = {}) {
    latestScrapeStatus = status;
    const isRunning = Boolean(status.running);
    setScrapeBusy(isRunning);

    const panel = document.getElementById('scrapeStatusPanel');
    const title = document.getElementById('scrapeStatusTitle');
    const detail = document.getElementById('scrapeStatusDetail');
    const count = document.getElementById('scrapeStatusCount');
    const progress = document.getElementById('scrapeStatusProgress');
    const elapsed = document.getElementById('scrapeStatusElapsed');
    const pulse = document.getElementById('scrapeStatusPulse');
    if (!panel || !title || !detail || !count) return;

    if (!isRunning && !status.last_error) {
        panel.classList.add('hidden');
        stopScrapeUiTicker();
        return;
    }

    panel.classList.remove('hidden');
    if (status.last_error && !isRunning) {
        title.textContent = 'Wyszukiwanie przerwane';
        detail.textContent = status.last_error;
        count.textContent = '';
        if (progress) progress.style.width = '0%';
        if (elapsed) elapsed.textContent = 'Czas: --:--';
        if (pulse) pulse.textContent = '';
        stopScrapeUiTicker();
        return;
    }

    if (isRunning) {
        startScrapeUiTicker();
    }

    const currentWebsite = status.current_website || 'Przygotowanie...';
    const completed = Number(status.completed || 0);
    const total = Number(status.total || 0);
    const percent = total ? Math.max(2, Math.min(100, Math.round((completed / total) * 100))) : 6;
    title.textContent = 'Szukanie nowych ofert';
    detail.textContent = `Aktualnie sprawdzane: ${currentWebsite}`;
    count.textContent = total ? `${completed}/${total}` : '';
    if (progress) progress.style.width = `${percent}%`;
    if (elapsed) elapsed.textContent = `Czas: ${formatElapsed(status.started_at)}`;
    if (pulse) pulse.textContent = `Praca w tle${'.'.repeat((Math.floor(Date.now() / 1000) % 3) + 1)}`;
}

function formatElapsed(startedAt) {
    if (!startedAt) return '00:00';
    const started = new Date(startedAt);
    if (Number.isNaN(started.getTime())) return '00:00';
    const totalSeconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${minutes}:${seconds}`;
}

function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
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
