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
            .replace(/\b(stoğa|stoga|stoktan|stok|ekle|giriş|giris|çıkış|cikis|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye)\b/gi, ' ')
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
            this.recognition = null;
        }

        init() {
            if (!this.panel || !this.input || !this.result) return;
            this.bindEvents();
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
                });
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
            const result = await this.analyzeWithApi(command);
            this.renderResult(result);
            if (!command.trim() && window.showToast) {
                window.showToast('Önce bir komut yaz kral.', 'warning', 3500);
            }
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
                note: result.note || 'Bu sürümde işlem yapılmaz, sadece analiz edilir.'
            };
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
                    ${routeHtml}
                    <div class="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/25 dark:text-amber-200">
                        <span class="font-black">Güvenlik:</span> Kullanıcı onayı olmadan hiçbir stok, cari veya kasa işlemi yapılmaz.
                    </div>
                    <p class="text-xs font-semibold leading-5 text-slate-500 dark:text-slate-400">${escapeHtml(result.note)}</p>
                </div>
            `;
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
