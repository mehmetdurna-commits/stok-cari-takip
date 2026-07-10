(function () {
    'use strict';

    const DEFAULT_RESULT = {
        intent: 'unknown',
        title: 'Komutu netleştiremedim',
        confidence: 'Düşük',
        summary: 'Bu komutu güvenli şekilde işleme çevirmek için biraz daha açık yazman gerekiyor.',
        fields: [
            ['İşlem Türü', 'Belirsiz'],
            ['Durum', 'Onay Bekliyor']
        ],
        routeHint: '',
        note: 'Bu sürümde işlem yapılmaz, sadece analiz edilir.'
    };

    function normalizeCommand(value) {
        return String(value || '')
            .toLocaleLowerCase('tr-TR')
            .replace(/[’']/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function extractAmount(text) {
        const match = String(text || '').match(/(\d+(?:[.,]\d+)?)\s*(tl|lira|₺|adet|tane)?/i);
        if (!match) return null;
        return {
            value: Number(String(match[1]).replace(',', '.')),
            unit: match[2] || ''
        };
    }

    function cleanEntity(text) {
        return String(text || '')
            .replace(/\b(stoğa|stoga|stoktan|stok|ürün|urun|ekle|giriş|giris|çıkış|cikis|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|sat|satış|satis|pos|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye|teklif|oluştur|olustur|hazırla|hazirla|cari|müşteri|musteri)\b/gi, ' ')
            .replace(/\d+(?:[.,]\d+)?/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function formatAmount(amount, fallbackUnit) {
        if (!amount) return 'Eksik';
        const unit = fallbackUnit || amount.unit || '';
        return `${amount.value} ${unit}`.trim();
    }

    function createAnalysisResult(overrides) {
        return Object.assign({}, DEFAULT_RESULT, overrides || {});
    }

    function analyzeCommand(command) {
        const raw = String(command || '').trim();
        const text = normalizeCommand(raw);
        const amount = extractAmount(text);

        if (!text) {
            return createAnalysisResult({
                summary: 'Önce bir komut yazmalı veya söylemelisin.',
                fields: [
                    ['İşlem Türü', 'Belirsiz'],
                    ['Durum', 'Komut Bekleniyor']
                ]
            });
        }

        if ((text.includes('stoğa') || text.includes('stoga') || text.includes('stok')) && (text.includes('ekle') || text.includes('giriş') || text.includes('giris'))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'stock_in',
                title: 'Stok girişi taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için stok girişi taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Stok Girişi'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/stok/giris'
            });
        }

        if ((text.includes('stoktan') || text.includes('stok')) && (text.includes('düş') || text.includes('dus') || text.includes('çıkış') || text.includes('cikis'))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'stock_out',
                title: 'Stok çıkışı taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için stok çıkışı taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Stok Çıkışı'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/stok/cikis'
            });
        }

        if (text.includes('tahsilat') || (text.includes('müşteri') && text.includes('al'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'collection',
                title: 'Müşteriden tahsilat taslağı',
                confidence: customer && amount ? 'Yüksek' : 'Orta',
                summary: `${customer || 'Seçilecek cari'} için tahsilat taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Müşteriden Tahsilat'],
                    ['Cari', customer || 'Eksik'],
                    ['Tutar', formatAmount(amount, 'TL')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        if (text.includes('ödeme') || text.includes('odeme') || text.includes('tedarikçi') || text.includes('tedarikci')) {
            const supplier = cleanEntity(text);
            return createAnalysisResult({
                intent: 'supplier_payment',
                title: 'Tedarikçiye ödeme taslağı',
                confidence: supplier && amount ? 'Yüksek' : 'Orta',
                summary: `${supplier || 'Seçilecek tedarikçi'} için ödeme taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Tedarikçiye Ödeme'],
                    ['Cari', supplier || 'Eksik'],
                    ['Tutar', formatAmount(amount, 'TL')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        const isSaleQuery = text.includes('göster') || text.includes('goster') || text.includes('listele') || text.includes('bugünkü') || text.includes('bugunku') || text.includes('günlük') || text.includes('gunluk');
        if (!isSaleQuery && (text.includes('satış') || text.includes('satis') || text.includes('pos') || /\bsat\b/.test(text))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'pos_sale',
                title: 'Hızlı satış taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için POS satış taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Hızlı Satış'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/pos'
            });
        }

        if (text.includes('teklif') && (text.includes('oluştur') || text.includes('olustur') || text.includes('hazırla') || text.includes('hazirla') || text.includes('aç') || text.includes('ac'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'quote',
                title: 'Teklif oluşturma taslağı',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Seçilecek cari'} için teklif oluşturma taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Teklif Oluştur'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/teklif/ekle'
            });
        }

        if ((text.includes('cari') || text.includes('müşteri') || text.includes('musteri')) && (text.includes('ekle') || text.includes('oluştur') || text.includes('olustur') || text.includes('aç') || text.includes('ac'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'cari_create',
                title: 'Cari ekleme taslağı',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Yeni cari'} için cari kartı açma taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Cari Ekle'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cari-ekle'
            });
        }

        if (text.includes('bugünkü satış') || text.includes('bugunku satis') || text.includes('günlük satış') || text.includes('gunluk satis')) {
            return createAnalysisResult({
                intent: 'daily_sales',
                title: 'Günlük satış sorgusu',
                confidence: 'Yüksek',
                summary: 'Bugünkü satışlar için sorgu taslağı hazırlandı.',
                fields: [
                    ['İşlem Türü', 'Bilgi Sorgusu'],
                    ['Ekran', 'Günlük Satışlar'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/gunluk-satislar'
            });
        }

        if (text.includes('kritik stok') || text.includes('azalan stok')) {
            return createAnalysisResult({
                intent: 'critical_stock',
                title: 'Kritik stok sorgusu',
                confidence: 'Yüksek',
                summary: 'Kritik stoktaki ürünler için sorgu taslağı hazırlandı.',
                fields: [
                    ['İşlem Türü', 'Bilgi Sorgusu'],
                    ['Filtre', 'Kritik Stok'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/urunler'
            });
        }

        if (text.includes('bakiye') || text.includes('borcu') || text.includes('alacağı') || text.includes('alacagi')) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'customer_balance',
                title: 'Cari bakiye sorgusu',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Seçilecek cari'} için bakiye sorgusu taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Cari Bakiye Sorgusu'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        return createAnalysisResult();
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    class AssistantPanel {
        constructor(options) {
            this.options = Object.assign({
                panelId: 'voice-assistant-panel',
                inputId: 'voice-assistant-input',
                resultId: 'voice-assistant-result',
                micId: 'voice-assistant-mic',
                listeningId: 'voice-assistant-listening',
                fabId: 'voice-assistant-fab'
            }, options || {});
            this.panel = document.getElementById(this.options.panelId);
            this.input = document.getElementById(this.options.inputId);
            this.result = document.getElementById(this.options.resultId);
            this.micButton = document.getElementById(this.options.micId);
            this.listening = document.getElementById(this.options.listeningId);
            this.fab = document.getElementById(this.options.fabId);
            this.analyzeButton = this.panel ? this.panel.querySelector('[data-assistant-action="analyze"]') : null;
            this.recognition = null;
            this.currentResult = null;
            this.selectedCandidate = null;
            this.historyKey = 'esstok_assistant_recent_commands';
            this.history = this.loadHistory();
        }

        init() {
            if (!this.panel || !this.input || !this.result) return;
            this.bindEvents();
            this.renderWelcome();
            window.esstokAssistantPanel = this;
        }

        bindEvents() {
            document.querySelectorAll('[data-assistant-action]').forEach((element) => {
                element.addEventListener('click', () => {
                    const action = element.dataset.assistantAction;
                    if (action === 'open') this.open();
                    if (action === 'close') this.close();
                    if (action === 'toggle') this.toggle();
                    if (action === 'analyze') this.analyze();
                    if (action === 'example') this.fillExample(element.dataset.assistantExample || '');
                    if (action === 'mic') this.startListening();
                    if (action === 'clear') this.clear();
                });
            });

            this.result.addEventListener('click', (event) => {
                const candidateButton = event.target.closest('[data-assistant-candidate-index]');
                if (candidateButton) {
                    const index = Number(candidateButton.dataset.assistantCandidateIndex);
                    this.selectCandidate(index);
                    return;
                }

                const historyButton = event.target.closest('[data-assistant-history-index]');
                if (historyButton) {
                    const index = Number(historyButton.dataset.assistantHistoryIndex);
                    this.useHistory(index);
                }
            });

            this.input.addEventListener('keydown', (event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                    event.preventDefault();
                    this.analyze();
                }
            });

            document.addEventListener('keydown', (event) => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'Space') {
                    const target = event.target;
                    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
                    event.preventDefault();
                    this.open();
                }
                if (event.key === 'Escape' && !this.panel.classList.contains('hidden')) {
                    this.close();
                }
            });
        }

        open() {
            this.panel.classList.remove('hidden');
            if (this.fab) this.fab.setAttribute('aria-expanded', 'true');
            setTimeout(() => this.input.focus(), 80);
        }

        close() {
            this.panel.classList.add('hidden');
            if (this.fab) this.fab.setAttribute('aria-expanded', 'false');
        }

        toggle() {
            if (this.panel.classList.contains('hidden')) this.open();
            else this.close();
        }

        fillExample(text) {
            this.input.value = text || '';
            this.analyze();
        }

        async analyze() {
            const command = this.input.value || '';
            this.setAnalyzing(true);
            const result = await this.analyzeWithApi(command);
            this.currentResult = result;
            this.selectedCandidate = null;
            this.saveHistory(command);
            this.setAnalyzing(false);
            this.renderResult(result);
            if (!command.trim() && window.showToast) {
                window.showToast('Önce bir komut yaz kral.', 'warning', 3500);
            }
        }

        clear() {
            this.input.value = '';
            this.currentResult = null;
            this.selectedCandidate = null;
            this.renderWelcome();
            this.input.focus();
        }

        setAnalyzing(isAnalyzing) {
            if (!this.analyzeButton) return;
            this.analyzeButton.disabled = isAnalyzing;
            this.analyzeButton.classList.toggle('opacity-70', isAnalyzing);
            this.analyzeButton.classList.toggle('cursor-wait', isAnalyzing);
            this.analyzeButton.innerHTML = isAnalyzing
                ? '<span class="material-symbols-outlined text-lg animate-spin">progress_activity</span> Analiz Ediliyor'
                : '<span class="material-symbols-outlined text-lg">psychology</span> Analiz Et';
        }

        async analyzeWithApi(command) {
            try {
                const response = await fetch('/api/assistant/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ command })
                });
                if (!response.ok) throw new Error(`Assistant API ${response.status}`);
                const payload = await response.json();
                if (payload && payload.success && payload.result) {
                    return this.normalizeApiResult(payload.result);
                }
            } catch (error) {
                console.warn('Assistant API kullanılamadı, yerel analiz devrede:', error);
            }
            return analyzeCommand(command);
        }

        renderWelcome() {
            const historyHtml = this.renderHistory();
            this.result.innerHTML = `
                <div class="space-y-3">
                    <div class="flex items-start gap-3">
                        <span class="material-symbols-outlined rounded-2xl bg-primary-50 p-2 text-primary-600 dark:bg-primary-950/40 dark:text-primary-300">tips_and_updates</span>
                        <div>
                            <p class="font-black text-slate-800 dark:text-white">Esstok Konuş hazır.</p>
                            <p class="mt-1 leading-6">Komutu yaz veya söyle; ben önce anladığım işlemi taslak olarak göstereyim.</p>
                        </div>
                    </div>
                    <div class="grid gap-2 sm:grid-cols-3">
                        <div class="rounded-2xl bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">Kayıt yapmaz</div>
                        <div class="rounded-2xl bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 dark:bg-blue-950/30 dark:text-blue-300">Önce analiz eder</div>
                        <div class="rounded-2xl bg-amber-50 px-3 py-2 text-xs font-bold text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">Onay ister</div>
                    </div>
                    ${historyHtml}
                </div>
            `;
        }

        normalizeApiResult(result) {
            return {
                intent: result.intent || 'unknown',
                title: result.title || 'Komut analizi',
                confidence: result.confidence || 'Düşük',
                summary: result.summary || '',
                fields: Array.isArray(result.fields) ? result.fields.map((field) => {
                    if (Array.isArray(field)) return field;
                    return [field.label || '', field.value || ''];
                }) : [],
                routeHint: result.route_hint || result.routeHint || '',
                note: result.note || 'Bu sürümde işlem yapılmaz, sadece analiz edilir.',
                matchStatus: result.match_status || '',
                candidateType: result.candidate_type || '',
                candidates: Array.isArray(result.candidates) ? result.candidates : [],
                missingFields: Array.isArray(result.missing_fields) ? result.missing_fields : [],
                requiresMatch: Boolean(result.requires_match),
                draftReady: Boolean(result.draft_ready)
            };
        }

        selectCandidate(index) {
            if (!this.currentResult || !Array.isArray(this.currentResult.candidates)) return;
            const candidate = this.currentResult.candidates[index];
            if (!candidate) return;
            this.selectedCandidate = candidate;
            this.renderResult(this.currentResult);
        }

        renderResult(result) {
            const confidenceClass = result.confidence === 'Yüksek'
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : (result.confidence === 'Orta'
                    ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300');
            const fieldsHtml = (result.fields || []).map((field) => {
                const label = Array.isArray(field) ? field[0] : field.label;
                const value = Array.isArray(field) ? field[1] : field.value;
                return `
                <div class="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-3 py-2 text-xs dark:bg-slate-950/50">
                    <span class="font-black uppercase tracking-wide text-slate-400">${escapeHtml(label)}</span>
                    <span class="text-right font-bold text-slate-900 dark:text-white">${escapeHtml(value)}</span>
                </div>
            `;
            }).join('');
            const routeHtml = result.routeHint ? `
                <div class="rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 dark:border-blue-900/40 dark:bg-blue-950/25 dark:text-blue-300">
                    Önerilen ekran: <span class="font-black">${escapeHtml(result.routeHint)}</span>
                </div>
            ` : '';
            const candidatesHtml = this.renderCandidates(result);
            const selectedHtml = this.renderSelectedCandidate();
            const readinessHtml = this.renderReadiness(result);
            const actionPreviewHtml = this.renderActionPreview(result);
            const historyHtml = this.renderHistory();
            this.result.innerHTML = `
                <div class="space-y-3">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="text-xs font-black uppercase tracking-[0.18em] text-primary-600 dark:text-primary-300">Anladığım İşlem</p>
                            <h3 class="mt-1 text-lg font-black tracking-tight text-slate-950 dark:text-white">${escapeHtml(result.title)}</h3>
                        </div>
                        <span class="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-black ${confidenceClass}">${escapeHtml(result.confidence)}</span>
                    </div>
                    <div class="rounded-2xl bg-slate-900 px-4 py-3 text-sm font-bold leading-6 text-white dark:bg-white dark:text-slate-950">${escapeHtml(result.summary)}</div>
                    <div class="grid gap-2">${fieldsHtml}</div>
                    ${readinessHtml}
                    ${candidatesHtml}
                    ${selectedHtml}
                    ${actionPreviewHtml}
                    ${routeHtml}
                    ${historyHtml}
                    <div class="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/25 dark:text-amber-200">
                        <span class="font-black">Güvenlik:</span> Kullanıcı onayı olmadan hiçbir stok, cari veya kasa işlemi yapılmaz.
                    </div>
                    <p class="text-xs font-semibold leading-5 text-slate-500 dark:text-slate-400">${escapeHtml(result.note)}</p>
                </div>
            `;
        }

        loadHistory() {
            try {
                const parsed = JSON.parse(localStorage.getItem(this.historyKey) || '[]');
                return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 5) : [];
            } catch (error) {
                return [];
            }
        }

        saveHistory(command) {
            const value = String(command || '').trim();
            if (!value) return;
            this.history = [value]
                .concat(this.history.filter((item) => item !== value))
                .slice(0, 5);
            try {
                localStorage.setItem(this.historyKey, JSON.stringify(this.history));
            } catch (error) {
                console.warn('Asistan komut geçmişi kaydedilemedi:', error);
            }
        }

        useHistory(index) {
            const command = this.history[index];
            if (!command) return;
            this.input.value = command;
            this.analyze();
        }

        renderHistory() {
            if (!this.history.length) return '';
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Son Komutlar</p>
                        <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-black text-slate-500 dark:bg-slate-800 dark:text-slate-300">Bu cihaz</span>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        ${this.history.map((item, index) => `
                            <button type="button" data-assistant-history-index="${index}" class="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-bold text-slate-600 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-primary-900/60 dark:hover:bg-primary-950/20 dark:hover:text-primary-300">
                                ${escapeHtml(item)}
                            </button>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        renderReadiness(result) {
            const missing = result.missingFields || [];
            const matchNeeded = result.requiresMatch && !this.selectedCandidate;
            const ready = result.draftReady && !matchNeeded;
            const statusClass = ready
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300';
            const items = [];
            if (missing.length) {
                missing.forEach((field) => items.push(`Eksik alan: ${field}`));
            }
            if (matchNeeded) {
                items.push(result.candidateType === 'product' ? 'Ürün eşleşmesi seçilmeli' : 'Cari eşleşmesi seçilmeli');
            }
            if (!items.length) {
                items.push('Taslak analiz için yeterli görünüyor');
            }
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Taslak Kontrolü</p>
                        <span class="rounded-full px-2.5 py-1 text-[11px] font-black ${statusClass}">${ready ? 'Hazır' : 'Kontrol Gerekli'}</span>
                    </div>
                    <div class="space-y-1.5">
                        ${items.map((item) => `
                            <div class="flex items-center gap-2 text-xs font-bold text-slate-600 dark:text-slate-300">
                                <span class="material-symbols-outlined text-base ${ready ? 'text-emerald-500' : 'text-amber-500'}">${ready ? 'check_circle' : 'info'}</span>
                                ${escapeHtml(item)}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        renderCandidates(result) {
            if (!result.matchStatus && (!result.candidates || !result.candidates.length)) return '';
            const title = result.candidateType === 'product'
                ? 'Olası ürün eşleşmeleri'
                : (result.candidateType === 'cari' ? 'Olası cari eşleşmeleri' : 'Eşleşme durumu');
            const statusClass = result.candidates && result.candidates.length
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
            const items = (result.candidates || []).map((candidate, index) => {
                const isSelected = this.selectedCandidate && String(this.selectedCandidate.id) === String(candidate.id);
                return `
                <button type="button" data-assistant-candidate-index="${index}" class="w-full rounded-2xl border ${isSelected ? 'border-primary-300 bg-primary-50 ring-2 ring-primary-500/10 dark:border-primary-800 dark:bg-primary-950/20' : 'border-slate-200 bg-white hover:border-primary-200 hover:bg-blue-50/50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-primary-900/60 dark:hover:bg-primary-950/10'} px-3 py-2 text-left transition">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="truncate text-sm font-black text-slate-900 dark:text-white">${escapeHtml(candidate.label)}</p>
                            <p class="mt-0.5 truncate text-xs font-semibold text-slate-500 dark:text-slate-400">${escapeHtml(candidate.subtitle)}</p>
                        </div>
                        <div class="flex shrink-0 items-center gap-2">
                            ${candidate.meta ? `<span class="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-300">${escapeHtml(candidate.meta)}</span>` : ''}
                            <span class="material-symbols-outlined text-base ${isSelected ? 'text-primary-600' : 'text-slate-300'}">${isSelected ? 'check_circle' : 'radio_button_unchecked'}</span>
                        </div>
                    </div>
                </button>
            `;
            }).join('');
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">${title}</p>
                        <span class="rounded-full px-2.5 py-1 text-[11px] font-black ${statusClass}">${escapeHtml(result.matchStatus || 'Kontrol')}</span>
                    </div>
                    ${items || '<p class="text-xs font-semibold leading-5 text-slate-500 dark:text-slate-400">Bu komuta uygun kayıt bulunamadı. Daha net ürün/cari adı yazılırsa eşleşme güçlenir.</p>'}
                </div>
            `;
        }

        renderSelectedCandidate() {
            if (!this.selectedCandidate) return '';
            return `
                <div class="rounded-3xl border border-primary-100 bg-gradient-to-r from-primary-50 to-cyan-50 p-3 dark:border-primary-900/40 dark:from-primary-950/25 dark:to-cyan-950/20">
                    <p class="text-xs font-black uppercase tracking-[0.14em] text-primary-600 dark:text-primary-300">Seçili kayıt</p>
                    <div class="mt-2 flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="truncate text-sm font-black text-slate-950 dark:text-white">${escapeHtml(this.selectedCandidate.label)}</p>
                            <p class="mt-0.5 truncate text-xs font-semibold text-slate-600 dark:text-slate-300">${escapeHtml(this.selectedCandidate.subtitle)}</p>
                        </div>
                        <span class="material-symbols-outlined shrink-0 text-primary-600 dark:text-primary-300">verified</span>
                    </div>
                </div>
            `;
        }

        renderActionPreview(result) {
            if (!result || result.intent === 'unknown') return '';
            const isReady = (result.draftReady && (!result.requiresMatch || Boolean(this.selectedCandidate)));
            const safeRoute = this.safeInternalRoute(result.routeHint);
            const routeButton = result.routeHint ? `
                <a href="${escapeHtml(safeRoute)}" class="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-2xl border border-primary-100 bg-primary-50 px-3 py-2 text-xs font-black text-primary-700 transition hover:bg-primary-100 dark:border-primary-900/40 dark:bg-primary-950/25 dark:text-primary-300">
                    <span class="material-symbols-outlined text-base">open_in_new</span>
                    Ekrana Git
                </a>
            ` : '';
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="flex items-center justify-between gap-3">
                        <div>
                            <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Sonraki Faz Önizlemesi</p>
                            <p class="mt-1 text-sm font-bold text-slate-700 dark:text-slate-200">${isReady ? 'Bu taslak ileride onay kartına dönüşebilir.' : 'Önce doğru kayıt seçilmelidir.'}</p>
                        </div>
                        <div class="flex shrink-0 flex-col gap-2 sm:flex-row">
                            ${routeButton}
                            <button type="button" disabled class="rounded-2xl bg-slate-200 px-3 py-2 text-xs font-black text-slate-500 opacity-70 dark:bg-slate-800 dark:text-slate-400">
                                Onayla Pasif
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }

        safeInternalRoute(route) {
            const value = String(route || '').trim();
            if (!value.startsWith('/') || value.startsWith('//')) return '#';
            return value;
        }

        startListening() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                if (window.showToast) {
                    window.showToast('Bu tarayıcı sesli komutu desteklemiyor. Şimdilik komutu yazarak analiz edebilirsin.', 'warning', 5000);
                }
                return;
            }
            this.recognition = new SpeechRecognition();
            this.recognition.lang = 'tr-TR';
            this.recognition.interimResults = false;
            this.recognition.maxAlternatives = 1;
            if (this.listening) this.listening.classList.remove('hidden');
            if (this.micButton) this.micButton.classList.add('animate-pulse');
            this.recognition.onresult = (event) => {
                const transcript = event.results && event.results[0] && event.results[0][0] ? event.results[0][0].transcript : '';
                if (transcript) this.input.value = transcript;
                this.analyze();
            };
            this.recognition.onerror = () => {
                if (window.showToast) window.showToast('Sesi alamadım kral. Tekrar dene veya komutu yaz.', 'warning', 4500);
            };
            this.recognition.onend = () => {
                if (this.listening) this.listening.classList.add('hidden');
                if (this.micButton) this.micButton.classList.remove('animate-pulse');
            };
            this.recognition.start();
        }
    }

    window.AssistantPanel = AssistantPanel;
    window.EsstokAssistantParser = { analyzeCommand };

    document.addEventListener('DOMContentLoaded', () => {
        const assistant = new AssistantPanel();
        assistant.init();
    });
})();
