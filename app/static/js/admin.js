let adminScrapeStatusTimer = null;
let adminScrapeUiTimer = null;
let adminLatestScrapeStatus = {};

document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadWebsites();
    loadCities();
    pollScrapeStatus();

    window.triggerScrape = triggerScrape;
    window.editWebsite = editWebsite;
    window.deleteWebsite = deleteWebsite;
    window.editCity = editCity;
    window.deleteCity = deleteCity;
    window.bulkSetWebsitesActive = bulkSetWebsitesActive;
    window.bulkSetCitiesActive = bulkSetCitiesActive;
    window.updateSelectedWebsitesCount = updateSelectedWebsitesCount;
    window.updateSelectedCitiesCount = updateSelectedCitiesCount;
    window.shutdownApp = shutdownApp;

    setupSelectAll('selectAllWebsites', '.website-check', updateSelectedWebsitesCount);
    setupSelectAll('selectAllCities', '.city-check', updateSelectedCitiesCount);

    document.getElementById('websiteForm').addEventListener('submit', saveWebsite);
    document.getElementById('cityForm').addEventListener('submit', saveCity);
    document.getElementById('cancelWebsiteEdit').addEventListener('click', clearWebsiteForm);
    document.getElementById('cancelCityEdit').addEventListener('click', clearCityForm);
});

async function loadStats() {
    try {
        const res = await fetch('/api/admin/stats');
        const stats = await res.json();
        document.getElementById('totalOffers').textContent = stats.total_offers;
        document.getElementById('activeWebsites').textContent = stats.active_websites;
        document.getElementById('activeCities').textContent = stats.active_cities;
    } catch (err) {
        console.error('Failed to load stats:', err);
    }
}

async function saveWebsite(event) {
    event.preventDefault();
    const id = document.getElementById('websiteId').value;
    const data = {
        url: document.getElementById('websiteUrl').value,
        company_name: document.getElementById('websiteCompany').value,
        category: document.getElementById('websiteCategory').value,
        keywords: document.getElementById('websiteKeywords').value,
        location: document.getElementById('websiteLocation').value,
        custom_config: document.getElementById('websiteCustomConfig').value || '{}',
        active: document.getElementById('websiteActive').checked
    };

    const res = await fetch(id ? `/api/admin/websites/${id}` : '/api/admin/websites', {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    if (!res.ok) {
        const err = await res.json();
        alert('Blad zapisu strony: ' + (err.detail || 'Nieznany blad'));
        return;
    }

    clearWebsiteForm();
    await loadWebsites();
    await loadStats();
    alert('Strona zostala zapisana.');
}

async function loadWebsites() {
    try {
        const res = await fetch('/api/admin/websites');
        const sites = await res.json();
        const body = document.getElementById('websitesTableBody');

        if (!sites.length) {
            body.innerHTML = '<tr><td colspan="6" class="px-6 py-4 text-center text-gray-500">Brak skonfigurowanych stron.</td></tr>';
            updateSelectedWebsitesCount();
            return;
        }

        body.innerHTML = sites.map(site => `
            <tr>
                <td class="px-6 py-4 whitespace-nowrap">
                    <input type="checkbox" value="${site.id}" aria-label="Wybierz ${escapeAttribute(site.company_name)}" class="website-check h-4 w-4 rounded text-blue-600 focus:ring-blue-500" onchange="updateSelectedWebsitesCount()">
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${escapeHtml(site.company_name)}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-blue-600 truncate max-w-xs">
                    <a href="${escapeAttribute(site.url)}" target="_blank">${escapeHtml(site.url)}</a>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${escapeHtml(site.category)}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${site.active ? 'Tak' : 'Nie'}</td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button onclick="editWebsite(${site.id})" class="text-blue-600 hover:text-blue-900 mr-3">Edytuj</button>
                    <button onclick="deleteWebsite(${site.id})" class="text-red-600 hover:text-red-900">Usun</button>
                </td>
            </tr>
        `).join('');
        updateSelectedWebsitesCount();
    } catch (err) {
        console.error('Failed to load websites:', err);
    }
}

async function editWebsite(id) {
    try {
        const res = await fetch(`/api/admin/websites/${id}`);
        if (!res.ok) {
            const err = await res.json();
            alert('Blad pobierania strony: ' + (err.detail || res.statusText));
            return;
        }

        const site = await res.json();
        document.getElementById('websiteId').value = site.id;
        document.getElementById('websiteUrl').value = site.url;
        document.getElementById('websiteCompany').value = site.company_name;
        document.getElementById('websiteCategory').value = site.category;
        document.getElementById('websiteKeywords').value = site.keywords || '';
        document.getElementById('websiteLocation').value = site.location || '';
        document.getElementById('websiteCustomConfig').value = site.custom_config || '{}';
        document.getElementById('websiteActive').checked = site.active;
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
        console.error('Failed to fetch website for edit:', err);
    }
}

async function deleteWebsite(id) {
    if (!confirm('Czy na pewno chcesz usunac te strone?')) return;

    await fetch(`/api/admin/websites/${id}`, { method: 'DELETE' });
    await loadWebsites();
    await loadStats();
}

function clearWebsiteForm() {
    document.getElementById('websiteId').value = '';
    document.getElementById('websiteForm').reset();
}

async function saveCity(event) {
    event.preventDefault();
    const id = document.getElementById('cityId').value;
    const data = {
        city_name: document.getElementById('cityName').value,
        latitude: parseFloat(document.getElementById('cityLat').value),
        longitude: parseFloat(document.getElementById('cityLon').value),
        active: document.getElementById('cityActive').checked
    };

    const res = await fetch(id ? `/api/admin/cities/${id}` : '/api/admin/cities', {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    if (!res.ok) {
        const err = await res.json();
        alert('Blad zapisu miasta: ' + (err.detail || 'Nieznany blad'));
        return;
    }

    clearCityForm();
    await loadCities();
    await loadStats();
    alert('Miasto zostalo zapisane.');
}

async function loadCities() {
    try {
        const res = await fetch('/api/admin/cities');
        const cities = await res.json();
        const body = document.getElementById('citiesTableBody');

        if (!cities.length) {
            body.innerHTML = '<tr><td colspan="6" class="px-6 py-4 text-center text-gray-500">Brak skonfigurowanych miast.</td></tr>';
            updateSelectedCitiesCount();
            return;
        }

        body.innerHTML = cities.map(city => `
            <tr>
                <td class="px-6 py-4 whitespace-nowrap">
                    <input type="checkbox" value="${city.id}" aria-label="Wybierz ${escapeAttribute(city.city_name)}" class="city-check h-4 w-4 rounded text-blue-600 focus:ring-blue-500" onchange="updateSelectedCitiesCount()">
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${escapeHtml(city.city_name)}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${city.latitude}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${city.longitude}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${city.active ? 'Tak' : 'Nie'}</td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button onclick="editCity(${city.id})" class="text-blue-600 hover:text-blue-900 mr-3">Edytuj</button>
                    <button onclick="deleteCity(${city.id})" class="text-red-600 hover:text-red-900">Usun</button>
                </td>
            </tr>
        `).join('');
        updateSelectedCitiesCount();
    } catch (err) {
        console.error('Failed to load cities:', err);
    }
}

async function editCity(id) {
    try {
        const res = await fetch(`/api/admin/cities/${id}`);
        if (!res.ok) {
            const err = await res.json();
            alert('Blad pobierania miasta: ' + (err.detail || res.statusText));
            return;
        }

        const city = await res.json();
        document.getElementById('cityId').value = city.id;
        document.getElementById('cityName').value = city.city_name;
        document.getElementById('cityLat').value = city.latitude;
        document.getElementById('cityLon').value = city.longitude;
        document.getElementById('cityActive').checked = city.active;
        window.scrollTo({ top: document.getElementById('cityForm').offsetTop - 100, behavior: 'smooth' });
    } catch (err) {
        console.error('Failed to fetch city for edit:', err);
    }
}

async function deleteCity(id) {
    if (!confirm('Czy na pewno chcesz usunac to miasto?')) return;

    await fetch(`/api/admin/cities/${id}`, { method: 'DELETE' });
    await loadCities();
    await loadStats();
}

function clearCityForm() {
    document.getElementById('cityId').value = '';
    document.getElementById('cityForm').reset();
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
    } catch (err) {
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
    if (adminScrapeStatusTimer) return;
    adminScrapeStatusTimer = window.setInterval(pollScrapeStatus, 2000);
}

function stopScrapeStatusPolling() {
    if (!adminScrapeStatusTimer) return;
    window.clearInterval(adminScrapeStatusTimer);
    adminScrapeStatusTimer = null;
}

function startScrapeUiTicker() {
    if (adminScrapeUiTimer) return;
    adminScrapeUiTimer = window.setInterval(() => renderScrapeStatus(adminLatestScrapeStatus), 1000);
}

function stopScrapeUiTicker() {
    if (!adminScrapeUiTimer) return;
    window.clearInterval(adminScrapeUiTimer);
    adminScrapeUiTimer = null;
}

async function pollScrapeStatus() {
    try {
        const response = await fetch('/api/admin/scrape-status');
        if (!response.ok) return;
        const status = await response.json();
        renderScrapeStatus(status);

        if (status.running) {
            startScrapeStatusPolling();
            return;
        }

        stopScrapeStatusPolling();
        loadStats();
    } catch (error) {
        console.error('Failed to load scrape status:', error);
    }
}

function renderScrapeStatus(status = {}) {
    adminLatestScrapeStatus = status;
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

async function shutdownApp() {
    if (!confirm('Zatrzymać aplikację działającą w tle? Strona przestanie odpowiadać do czasu ponownego uruchomienia skrótem.')) {
        return;
    }

    const btn = document.getElementById('shutdownBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Zatrzymywanie...';
        btn.classList.remove('bg-red-600', 'hover:bg-red-700');
        btn.classList.add('bg-gray-400', 'cursor-not-allowed');
    }

    try {
        await fetch('/api/admin/shutdown', { method: 'POST' });
        showShutdownMessage();
    } catch (err) {
        showShutdownMessage();
    }
}

function showShutdownMessage() {
    const existing = document.getElementById('shutdownNotice');
    if (existing) return;

    const notice = document.createElement('div');
    notice.id = 'shutdownNotice';
    notice.className = 'mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800';
    notice.textContent = 'Aplikacja została zatrzymana. Uruchom ją ponownie ze skrótu na pulpicie.';

    const main = document.querySelector('main');
    if (main) {
        main.prepend(notice);
    }
}

function setupSelectAll(selectAllId, itemSelector, countUpdater) {
    const selectAll = document.getElementById(selectAllId);
    if (!selectAll) return;

    selectAll.addEventListener('change', event => {
        document.querySelectorAll(itemSelector).forEach(checkbox => {
            checkbox.checked = event.target.checked;
        });
        countUpdater();
    });
}

function getSelectedIds(selector) {
    return Array.from(document.querySelectorAll(`${selector}:checked`))
        .map(checkbox => parseInt(checkbox.value, 10));
}

function updateBulkCount(selectAllId, itemSelector, countId) {
    const checkboxes = Array.from(document.querySelectorAll(itemSelector));
    const selected = checkboxes.filter(checkbox => checkbox.checked);
    const selectAll = document.getElementById(selectAllId);

    if (selectAll) {
        selectAll.checked = checkboxes.length > 0 && selected.length === checkboxes.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
    }

    const counter = document.getElementById(countId);
    if (counter) {
        counter.textContent = `Zaznaczono: ${selected.length}`;
    }
}

function updateSelectedWebsitesCount() {
    updateBulkCount('selectAllWebsites', '.website-check', 'selectedWebsitesCount');
}

function updateSelectedCitiesCount() {
    updateBulkCount('selectAllCities', '.city-check', 'selectedCitiesCount');
}

async function bulkSetWebsitesActive(active) {
    const ids = getSelectedIds('.website-check');
    if (!ids.length) {
        alert('Wybierz co najmniej jedna strone.');
        return;
    }

    await bulkSetActive('/api/admin/websites/bulk/active', ids, active);
    await loadWebsites();
    await loadStats();
}

async function bulkSetCitiesActive(active) {
    const ids = getSelectedIds('.city-check');
    if (!ids.length) {
        alert('Wybierz co najmniej jedno miasto.');
        return;
    }

    await bulkSetActive('/api/admin/cities/bulk/active', ids, active);
    await loadCities();
    await loadStats();
}

async function bulkSetActive(url, ids, active) {
    const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids, active })
    });

    if (!res.ok) {
        const err = await res.json();
        alert('Blad aktualizacji: ' + (err.detail || 'Nieznany blad'));
    }
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

function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}
