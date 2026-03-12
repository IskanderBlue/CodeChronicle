import * as pdfjsLib from 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/5.4.149/pdf.min.mjs';
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/5.4.149/pdf.worker.min.mjs';

const PDF_DB_NAME = 'codechronicle_pdf_cache';
const PDF_DB_VERSION = 1;
const PDF_DB_STORE = 'pdf_mappings';
const mappingRegistry = new Map();
const pdfDocumentCache = new Map();
let dbPromise = null;

function normalizeFilename(filename) {
    return (filename || '').trim().toLowerCase();
}

function expectedKeyFor(filename) {
    return normalizeFilename(filename);
}

function humanBytes(value) {
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit += 1;
    }
    const decimals = unit === 0 ? 0 : 1;
    return `${size.toFixed(decimals)} ${units[unit]}`;
}

function getPdfDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(PDF_DB_NAME, PDF_DB_VERSION);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(PDF_DB_STORE)) {
                db.createObjectStore(PDF_DB_STORE, { keyPath: 'expected_key' });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('Could not open IndexedDB.'));
    });
    return dbPromise;
}

async function idbReadAllMappings() {
    const db = await getPdfDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PDF_DB_STORE, 'readonly');
        const store = tx.objectStore(PDF_DB_STORE);
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error || new Error('Could not read PDF mappings.'));
    });
}

async function idbPutMapping(record) {
    const db = await getPdfDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PDF_DB_STORE, 'readwrite');
        tx.oncomplete = () => resolve(undefined);
        tx.onerror = () => reject(tx.error || new Error('Could not store PDF mapping.'));
        tx.objectStore(PDF_DB_STORE).put(record);
    });
}

async function idbDeleteMapping(expectedKey) {
    const db = await getPdfDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PDF_DB_STORE, 'readwrite');
        tx.oncomplete = () => resolve(undefined);
        tx.onerror = () => reject(tx.error || new Error('Could not delete PDF mapping.'));
        tx.objectStore(PDF_DB_STORE).delete(expectedKey);
    });
}

async function idbClearMappings() {
    const db = await getPdfDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(PDF_DB_STORE, 'readwrite');
        tx.oncomplete = () => resolve(undefined);
        tx.onerror = () => reject(tx.error || new Error('Could not clear PDF mappings.'));
        tx.objectStore(PDF_DB_STORE).clear();
    });
}

function getMapping(expectedFilename) {
    return mappingRegistry.get(expectedKeyFor(expectedFilename)) || null;
}

function clearPdfDocumentCache(expectedKey) {
    for (const key of [...pdfDocumentCache.keys()]) {
        if (key.startsWith(`${expectedKey}:`)) {
            pdfDocumentCache.delete(key);
        }
    }
}

export async function savePdfMapping(expectedFilename, file) {
    const expected_key = expectedKeyFor(expectedFilename);
    if (!expected_key || !file) return;
    const record = {
        expected_key,
        expected_filename: expectedFilename,
        selected_filename: file.name || expectedFilename,
        blob: file,
        updated_at: Date.now(),
        size: Number(file.size) || 0,
    };
    await idbPutMapping(record);
    mappingRegistry.set(expected_key, record);
    clearPdfDocumentCache(expected_key);
    document.dispatchEvent(new CustomEvent('pdf-mapped', {
        detail: { expectedFilename, expectedKey: expected_key },
    }));
}

export async function clearPdfMapping(expectedFilename) {
    const expected_key = expectedKeyFor(expectedFilename);
    if (!expected_key) return;
    await idbDeleteMapping(expected_key);
    mappingRegistry.delete(expected_key);
    clearPdfDocumentCache(expected_key);
    document.dispatchEvent(new CustomEvent('pdf-mapped', {
        detail: { expectedFilename, expectedKey: expected_key },
    }));
}

export async function restorePdfMappings() {
    try {
        const records = await idbReadAllMappings();
        records.forEach(record => {
            if (record && record.expected_key && record.blob instanceof Blob) {
                mappingRegistry.set(record.expected_key, record);
            }
        });
    } catch (err) {
        console.error('Could not restore local PDF mappings:', err);
    }
}

function parsePdfFloat(value) {
    if (value === null || value === undefined || value === '') return null;
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function parsePdfPage(value) {
    const page = parseInt(value, 10);
    return Number.isFinite(page) && page > 0 ? page : 1;
}

function showPdfWarning(container, message) {
    const block = container.closest('[data-pdf-block]');
    if (!block) return;
    const warning = block.querySelector('[data-pdf-warning]');
    if (!warning) return;
    warning.textContent = message || '';
    warning.classList.toggle('hidden', !message);
}

function setFallbackVisibility(block, visible) {
    const fallback = block.querySelector('[data-pdf-fallback]');
    if (fallback) {
        fallback.classList.toggle('hidden', !visible);
    }
}

function setMappedLabel(block) {
    const container = block.querySelector('[data-pdf-container]');
    const expectedFilename = container?.getAttribute('data-pdf-expected-filename') || '';
    const mapping = getMapping(expectedFilename);
    const label = block.querySelector('[data-pdf-mapped-label]');
    if (label) {
        label.textContent = mapping
            ? `Mapped to: ${mapping.selected_filename}`
            : 'Not mapped yet.';
    }
}

function hideMismatchPrompt(block) {
    const mismatch = block.querySelector('[data-pdf-mismatch]');
    if (mismatch) mismatch.classList.add('hidden');
    block._pendingPdfFile = null;
}

function showMismatchPrompt(block, expectedFilename, selectedFilename) {
    const mismatch = block.querySelector('[data-pdf-mismatch]');
    if (!mismatch) return;
    const text = mismatch.querySelector('[data-pdf-mismatch-text]');
    if (text) {
        text.textContent = `Selected file "${selectedFilename}" does not match expected "${expectedFilename}".`;
    }
    mismatch.classList.remove('hidden');
}

function renderBlockControls(block, state) {
    const mount = block.querySelector('[data-pdf-controls-mount]');
    if (!mount) return;
    const container = block.querySelector('[data-pdf-container]');
    const viewerMode = container && container.hasAttribute('data-pdf-viewer-mode');
    const wantsPicker = state === 'picker';

    if (viewerMode && !wantsPicker) {
        // In viewer mode when mapped, skip change/clear buttons — just show jump control
        mount.innerHTML = '';
        renderPageControls(block, mount, false);
        return;
    }

    const pickerTemplate = block.querySelector('[data-pdf-picker-template]');
    const mappedTemplate = block.querySelector('[data-pdf-mapped-template]');
    const source = wantsPicker ? pickerTemplate : mappedTemplate;
    if (!source) return;
    mount.innerHTML = source.innerHTML;
    if (!wantsPicker) {
        hideMismatchPrompt(block);
    }
    renderPageControls(block, mount, wantsPicker);
    setMappedLabel(block);
}

function getResultSpan(container) {
    if (!container) return null;
    const startPage = parsePdfPage(container.getAttribute('data-pdf-page'));
    const rawEnd = container.getAttribute('data-pdf-page-end');
    const endPage = (rawEnd !== null && rawEnd !== '') ? parsePdfPage(rawEnd) : startPage;
    return {
        startPage,
        endPage,
        initialPageTop: parsePdfFloat(container.getAttribute('data-pdf-initial-page-top')),
        finalPageBottom: parsePdfFloat(container.getAttribute('data-pdf-final-page-bottom')),
    };
}

function getCurrentResultPage(block, span) {
    const fallback = span?.startPage || 1;
    const current = parsePdfPage(block?.dataset.currentPage || fallback);
    if (!span) return current;
    return Math.min(Math.max(current, span.startPage), span.endPage);
}

function renderPageControls(block, mount, wantsPicker) {
    const container = block.querySelector('[data-pdf-container]');
    const span = getResultSpan(container);
    if (!span || wantsPicker) return;
    const viewerMode = container.hasAttribute('data-pdf-viewer-mode');

    const currentPage = getCurrentResultPage(block, span);
    block.dataset.currentPage = String(currentPage);

    if (viewerMode) {
        // Viewer mode: jump-to-section button instead of change/clear mapping
        const nav = document.createElement('div');
        nav.className = 'flex items-center gap-3';

        const jumpBtn = document.createElement('button');
        jumpBtn.type = 'button';
        jumpBtn.className = 'inline-flex items-center px-2.5 py-1.5 text-xs font-medium rounded border border-primary-300 text-primary-700 hover:bg-primary-50 dark:border-primary-500 dark:text-primary-300 dark:hover:bg-primary-900/20';
        jumpBtn.textContent = 'Jump to section';
        jumpBtn.addEventListener('click', () => {
            const scrollBox = container.querySelector('[data-pdf-scale]');
            const targetSlot = scrollBox?.querySelector(`[data-pdf-slot-page="${span.startPage}"]`);
            if (scrollBox && targetSlot) {
                const pdfScale = parseFloat(scrollBox.dataset.pdfScale) || 1;
                const topOffset = span.initialPageTop != null ? span.initialPageTop * pdfScale : 0;
                scrollBox.scrollTo({ top: targetSlot.offsetTop + topOffset - 40, behavior: 'smooth' });
            }
        });

        const info = document.createElement('p');
        info.className = 'text-xs text-neutral-500 dark:text-neutral-400';
        const sectionRange = span.startPage === span.endPage
            ? `page ${span.startPage}`
            : `pages ${span.startPage}–${span.endPage}`;
        info.textContent = `Section on ${sectionRange}`;

        nav.appendChild(jumpBtn);
        nav.appendChild(info);
        mount.appendChild(nav);
        return;
    }

    // Card mode: prev/next buttons
    const nav = document.createElement('div');
    nav.className = 'mt-3 flex items-center justify-between gap-2 border-t border-neutral-200 pt-3 text-xs dark:border-neutral-700';

    const btnClass = 'inline-flex items-center px-2.5 py-1.5 text-xs font-medium rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-200 dark:border-neutral-600 dark:text-neutral-300 dark:hover:bg-neutral-700 disabled:opacity-50 disabled:cursor-not-allowed';

    const prevButton = document.createElement('button');
    prevButton.type = 'button';
    prevButton.dataset.pdfPrevPage = 'true';
    prevButton.className = btnClass;
    prevButton.textContent = 'Previous page';
    prevButton.disabled = currentPage <= span.startPage;

    const label = document.createElement('p');
    label.className = 'text-neutral-500 dark:text-neutral-400';
    label.textContent = span.startPage === span.endPage
        ? `Page ${currentPage}`
        : `Page ${currentPage} of ${span.startPage}-${span.endPage}`;

    const nextButton = document.createElement('button');
    nextButton.type = 'button';
    nextButton.dataset.pdfNextPage = 'true';
    nextButton.className = btnClass;
    nextButton.textContent = 'Next page';
    nextButton.disabled = currentPage >= span.endPage;

    nav.appendChild(prevButton);
    nav.appendChild(label);
    nav.appendChild(nextButton);
    mount.appendChild(nav);
}

function showUnmappedState(container) {
    container.innerHTML = '';
    container.classList.add('hidden');
}

async function loadPdfForExpectedFilename(expectedFilename) {
    const mapping = getMapping(expectedFilename);
    if (!mapping || !(mapping.blob instanceof Blob)) return null;
    const cacheKey = `${mapping.expected_key}:${mapping.updated_at}`;
    if (!pdfDocumentCache.has(cacheKey)) {
        const bytes = await mapping.blob.arrayBuffer();
        pdfDocumentCache.set(cacheKey, pdfjsLib.getDocument({ data: bytes }).promise);
    }
    return pdfDocumentCache.get(cacheKey);
}

/**
 * Render a single page element (canvas + text layer), optionally with bbox clipping.
 * Returns the wrapper div, or null on failure.
 */
async function buildPageElement(pdf, pageNum, containerWidth, opts = {}) {
    const { topClip = 0, bottomClip = 0, highlight = null } = opts;
    const page = await pdf.getPage(pageNum);
    const unscaledViewport = page.getViewport({ scale: 1 });
    const scale = containerWidth / unscaledViewport.width;
    const viewport = page.getViewport({ scale });
    const pageHeight = unscaledViewport.height;

    const visibleHeight = Math.max(40, viewport.height - topClip - bottomClip);
    const wrapper = document.createElement('div');
    wrapper.className = 'pdf-page';
    wrapper.dataset.pageNum = String(pageNum);
    wrapper.style.position = 'relative';
    wrapper.style.width = viewport.width + 'px';
    wrapper.style.height = visibleHeight + 'px';
    wrapper.style.overflow = 'hidden';

    const canvas = document.createElement('canvas');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * dpr);
    canvas.height = Math.floor(viewport.height * dpr);
    canvas.style.width = viewport.width + 'px';
    canvas.style.height = viewport.height + 'px';
    if (topClip > 0) canvas.style.marginTop = -topClip + 'px';
    wrapper.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    await page.render({ canvasContext: ctx, viewport }).promise;

    // Section highlight overlay
    if (highlight) {
        const el = document.createElement('div');
        el.style.cssText = `position:absolute;left:0;right:0;top:${highlight.top}px;height:${highlight.height}px;border:2px solid rgba(59,130,246,0.5);background:rgba(59,130,246,0.06);pointer-events:none;z-index:1;`;
        wrapper.appendChild(el);
    }

    // Page number label
    const pageLabel = document.createElement('div');
    pageLabel.style.cssText = 'position:absolute;top:4px;right:8px;font-size:11px;color:rgba(100,100,100,0.7);pointer-events:none;z-index:2;';
    pageLabel.textContent = `p. ${pageNum}`;
    wrapper.appendChild(pageLabel);

    const textContent = await page.getTextContent();
    const textLayerDiv = document.createElement('div');
    textLayerDiv.className = 'textLayer';
    textLayerDiv.style.setProperty('--scale-factor', scale);
    if (topClip > 0) textLayerDiv.style.top = -topClip + 'px';
    wrapper.appendChild(textLayerDiv);

    const tl = new pdfjsLib.TextLayer({ textContentSource: textContent, container: textLayerDiv, viewport });
    await tl.render();

    return wrapper;
}

async function renderPdfPage(container, expectedFilename, pageNum, span) {
    try {
        const viewerMode = container.hasAttribute('data-pdf-viewer-mode');
        // Skip re-render if viewer mode scrollBox is already set up or render in progress
        if (viewerMode && (container.dataset.pdfRendering === 'true' || container.querySelector('[data-pdf-scale]'))) {
            return true;
        }

        if (viewerMode) {
            container.dataset.pdfRendering = 'true';
            // Unhide container early so clientWidth is accurate
            container.classList.remove('hidden');
        }

        const pdf = await loadPdfForExpectedFilename(expectedFilename);
        if (!pdf) {
            if (viewerMode) delete container.dataset.pdfRendering;
            showUnmappedState(container);
            const block = container.closest('[data-pdf-block]');
            if (block) {
                setFallbackVisibility(block, true);
                showPdfWarning(container, '');
                const mount = block.querySelector('[data-pdf-controls-mount]');
                if (mount && !mount.querySelector('[data-pdf-file-input]')) {
                    renderBlockControls(block, 'picker');
                }
            }
            return false;
        }

        const totalPages = pdf.numPages;
        pageNum = Math.max(1, Math.min(pageNum, totalPages));

        const containerWidth = container.clientWidth || container.parentElement?.clientWidth || 600;

        if (viewerMode) {
            // --- Viewer mode: scrollable container with all pages, lazy-rendered ---
            // Get page dimensions from first page (assumes uniform size)
            const firstPdfPage = await pdf.getPage(1);
            const firstVp = firstPdfPage.getViewport({ scale: 1 });
            const scale = containerWidth / firstVp.width;
            const scaledPageHeight = Math.round(firstVp.height * scale);
            const PAGE_GAP = 4;

            // Scrollable viewport
            const scrollBox = document.createElement('div');
            scrollBox.dataset.pdfScale = String(scale);
            scrollBox.style.cssText = `height:80vh;overflow-y:auto;overflow-x:hidden;background:#525659;`;

            // Create placeholder slots for every page
            const slots = [];
            for (let p = 1; p <= totalPages; p++) {
                const slot = document.createElement('div');
                slot.dataset.pdfSlotPage = String(p);
                slot.style.cssText = `width:100%;height:${scaledPageHeight}px;margin:0 auto ${PAGE_GAP}px;position:relative;background:#e5e7eb;`;

                // Page number label (shown while loading)
                const label = document.createElement('div');
                label.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:13px;color:#999;';
                label.textContent = `Page ${p}`;
                slot.appendChild(label);

                scrollBox.appendChild(slot);
                slots.push(slot);
            }

            container.innerHTML = '';
            container.appendChild(scrollBox);

            // Lazy render with IntersectionObserver
            const rendered = new Set();
            const observer = new IntersectionObserver(async (entries) => {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue;
                    const slot = entry.target;
                    const p = parseInt(slot.dataset.pdfSlotPage, 10);
                    if (rendered.has(p)) continue;
                    rendered.add(p);
                    observer.unobserve(slot);

                    try {
                        const slotWidth = slot.clientWidth || containerWidth;
                        const liveScale = slotWidth / firstVp.width;

                        const isStart = span && p === span.startPage;
                        const isEnd = span && p === span.endPage;
                        const topB = isStart ? span.initialPageTop : null;
                        const bottomB = isEnd ? span.finalPageBottom : null;

                        let highlight = null;
                        if (topB !== null || bottomB !== null) {
                            const hTop = topB !== null ? topB * liveScale : 0;
                            const hBot = bottomB !== null ? bottomB * liveScale : Math.round(firstVp.height * liveScale);
                            highlight = { top: hTop, height: hBot - hTop };
                        }
                        const wrapper = await buildPageElement(pdf, p, slotWidth, { highlight });
                        slot.innerHTML = '';
                        slot.appendChild(wrapper);
                        // Adjust slot to actual page height (may differ from page-1 estimate)
                        slot.style.height = 'auto';
                    } catch (err) {
                        console.error(`Failed to render page ${p}:`, err);
                    }
                }
            }, { root: scrollBox, rootMargin: '200px 0px' });

            for (const slot of slots) observer.observe(slot);

            // Scroll to section page (use live width for accurate offset)
            const targetSlot = slots[pageNum - 1];
            if (targetSlot) {
                requestAnimationFrame(() => {
                    const liveScale = (targetSlot.clientWidth || containerWidth) / firstVp.width;
                    const topOffset = span && span.initialPageTop != null
                        ? span.initialPageTop * liveScale : 0;
                    scrollBox.scrollTop = targetSlot.offsetTop + topOffset - 40;
                });
            }
        } else {
            // --- Card mode: single page with bbox clipping ---
            const isFirstPage = span && pageNum === span.startPage;
            const isLastPage = span && pageNum === span.endPage;
            const topBoundary = isFirstPage ? span.initialPageTop : null;
            const bottomBoundary = isLastPage ? span.finalPageBottom : null;

            const probePage = await pdf.getPage(pageNum);
            const probeVp = probePage.getViewport({ scale: 1 });
            const pScale = containerWidth / probeVp.width;
            const pageHeight = probeVp.height;

            const topClip = topBoundary === null ? 0 : Math.max(0, topBoundary * pScale);
            const bottomClip = bottomBoundary === null ? 0 : Math.max(0, (pageHeight - bottomBoundary) * pScale);

            const wrapper = await buildPageElement(pdf, pageNum, containerWidth, { topClip, bottomClip });
            container.innerHTML = '';
            container.appendChild(wrapper);
        }

        container.dataset.pdfTotalPages = String(totalPages);
        container.classList.remove('hidden');
        if (viewerMode) delete container.dataset.pdfRendering;
        const block = container.closest('[data-pdf-block]');
        if (block) {
            setFallbackVisibility(block, false);
            showPdfWarning(container, '');
            renderBlockControls(block, 'mapped');
        }
        return true;
    } catch (err) {
        if (container.hasAttribute('data-pdf-viewer-mode')) delete container.dataset.pdfRendering;
        const block = container.closest('[data-pdf-block]');
        showUnmappedState(container);
        if (block) {
            setFallbackVisibility(block, true);
            renderBlockControls(block, 'picker');
        }
        const detail = err && err.message ? err.message : 'Unknown PDF loading error.';
        showPdfWarning(container, detail);
        console.error('PDF render error:', err);
        return false;
    }
}

function isVisibleElement(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

export async function renderContainer(container) {
    if (!container) return;
    const expectedFilename = container.getAttribute('data-pdf-expected-filename') || '';
    const span = getResultSpan(container);
    const block = container.closest('[data-pdf-block]');
    const page = getCurrentResultPage(block, span);
    await renderPdfPage(container, expectedFilename, page, span);
}

async function handleFileCandidate(block, file, forceOverride = false) {
    if (!block || !file) return;
    const container = block.querySelector('[data-pdf-container]');
    if (!container) return;

    const expectedFilename = container.getAttribute('data-pdf-expected-filename') || '';
    const expectedNormalized = normalizeFilename(expectedFilename);
    const selectedNormalized = normalizeFilename(file.name);
    const isPdfFile = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');

    if (!isPdfFile) {
        showPdfWarning(container, 'Selected file is not a PDF.');
        return;
    }

    if (!forceOverride && expectedNormalized && selectedNormalized !== expectedNormalized) {
        block._pendingPdfFile = file;
        showMismatchPrompt(block, expectedFilename, file.name);
        return;
    }

    hideMismatchPrompt(block);
    await savePdfMapping(expectedFilename, file);
}

export function bindBlockControls(block) {
    if (block.dataset.pdfBound === 'true') return;
    block.dataset.pdfBound = 'true';

    const container = block.querySelector('[data-pdf-container]');
    if (!container) return;

    // Resolve filename at call time, not bind time — viewer mode updates
    // data-pdf-expected-filename when switching editions.
    const currentFilename = () => container.getAttribute('data-pdf-expected-filename') || '';

    block.addEventListener('change', async (event) => {
        const source = event.target instanceof Element ? event.target : null;
        if (!source) return;
        const fileInput = source.closest('[data-pdf-file-input]');
        if (!fileInput || !block.contains(fileInput)) return;
        const file = fileInput.files && fileInput.files[0];
        await handleFileCandidate(block, file, false);
        fileInput.value = '';
    });

    block.addEventListener('click', async (event) => {
        const source = event.target instanceof Element ? event.target : null;
        if (!source) return;
        const button = source.closest('button');
        if (!button || !block.contains(button)) return;

        if (button.matches('[data-pdf-clear-mapping]')) {
            await clearPdfMapping(currentFilename());
            return;
        }
        if (button.matches('[data-pdf-override-mapping]')) {
            if (block._pendingPdfFile) {
                await handleFileCandidate(block, block._pendingPdfFile, true);
            }
            return;
        }
        if (button.matches('[data-pdf-cancel-mapping]')) {
            hideMismatchPrompt(block);
            return;
        }
        if (button.matches('[data-pdf-show-picker]')) {
            renderBlockControls(block, 'picker');
            return;
        }
        if (button.matches('[data-pdf-prev-page]')) {
            const span = getResultSpan(container);
            if (!span) return;
            const viewerMode = container.hasAttribute('data-pdf-viewer-mode');
            const minPage = viewerMode ? 1 : span.startPage;
            block.dataset.currentPage = String(Math.max(minPage, getCurrentResultPage(block, span) - 1));
            await renderContainer(container);
            return;
        }
        if (button.matches('[data-pdf-next-page]')) {
            const span = getResultSpan(container);
            if (!span) return;
            const viewerMode = container.hasAttribute('data-pdf-viewer-mode');
            const nextPage = getCurrentResultPage(block, span) + 1;
            block.dataset.currentPage = String(viewerMode ? nextPage : Math.min(span.endPage, nextPage));
            await renderContainer(container);
        }
    });

    block.addEventListener('dragover', (event) => {
        const source = event.target instanceof Element ? event.target : null;
        if (!source) return;
        const dropzone = source.closest('[data-pdf-dropzone]');
        if (!dropzone || !block.contains(dropzone)) return;
        event.preventDefault();
        dropzone.classList.add('pdf-dropzone-active');
    });

    block.addEventListener('dragleave', (event) => {
        const source = event.target instanceof Element ? event.target : null;
        if (!source) return;
        const dropzone = source.closest('[data-pdf-dropzone]');
        if (!dropzone || !block.contains(dropzone)) return;
        dropzone.classList.remove('pdf-dropzone-active');
    });

    block.addEventListener('drop', async (event) => {
        const source = event.target instanceof Element ? event.target : null;
        if (!source) return;
        const dropzone = source.closest('[data-pdf-dropzone]');
        if (!dropzone || !block.contains(dropzone)) return;
        event.preventDefault();
        dropzone.classList.remove('pdf-dropzone-active');
        const file = event.dataTransfer?.files?.[0];
        await handleFileCandidate(block, file, false);
    });

    renderBlockControls(block, getMapping(currentFilename()) ? 'mapped' : 'picker');
}

export function refreshMappedLabels(expectedKey = null) {
    const blocks = document.querySelectorAll('[data-pdf-block]');
    blocks.forEach(block => {
        const container = block.querySelector('[data-pdf-container]');
        const key = expectedKeyFor(container?.getAttribute('data-pdf-expected-filename'));
        if (!expectedKey || expectedKey === key) {
            setMappedLabel(block);
        }
    });
    refreshBrowseButtons(expectedKey);
}

function refreshBrowseButtons(expectedKey = null) {
    const buttons = document.querySelectorAll('[data-browse-expected-filename]');
    buttons.forEach(wrapper => {
        const filename = wrapper.getAttribute('data-browse-expected-filename');
        const key = expectedKeyFor(filename);
        if (expectedKey && key !== expectedKey) return;
        wrapper.classList.toggle('hidden', !getMapping(filename));
    });
}

// --- Lazy card rendering via IntersectionObserver ---
let _cardObserver = null;
const _pendingCards = new WeakSet();

function getCardObserver() {
    if (_cardObserver) return _cardObserver;
    _cardObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const block = entry.target;
            _cardObserver.unobserve(block);
            _pendingCards.delete(block);
            const container = block.querySelector('[data-pdf-container]');
            if (container) renderContainer(container);
        }
    }, { rootMargin: '300px 0px' });
    return _cardObserver;
}

export async function refreshMatchingVisibleContainers(expectedKey = null, root = null) {
    const scope = root || document;
    const containers = scope.querySelectorAll('[data-pdf-container]');
    for (const container of containers) {
        const key = expectedKeyFor(container.getAttribute('data-pdf-expected-filename'));
        if (expectedKey && key !== expectedKey) continue;
        const block = container.closest('[data-pdf-block]');
        if (!isVisibleElement(block || container)) continue;
        await renderContainer(container);
        // Yield to browser between renders to avoid "slowing down" warnings
        await new Promise(r => setTimeout(r, 0));
    }
}

export async function updateStorageUi() {
    const controls = document.querySelector('[data-pdf-storage-controls]');
    if (!controls) return;
    controls.classList.remove('hidden');

    const entryCount = mappingRegistry.size;
    const usageLabel = controls.querySelector('[data-pdf-storage-usage]');
    const engineLabel = controls.querySelector('[data-pdf-storage-engine]');
    const clearButton = controls.querySelector('[data-pdf-clear-cache]');

    let estimateText = `${entryCount} mapped file${entryCount === 1 ? '' : 's'}`;
    if (navigator.storage?.estimate) {
        try {
            const estimate = await navigator.storage.estimate();
            const used = humanBytes(estimate?.usage || 0);
            const quota = humanBytes(estimate?.quota || 0);
            estimateText += ` | Storage: ${used} / ${quota}`;
        } catch (err) {
            console.error('Storage estimate failed:', err);
        }
    }

    if (usageLabel) usageLabel.textContent = estimateText;
    if (engineLabel) {
        const opfsAvailable = !!(navigator.storage && navigator.storage.getDirectory);
        engineLabel.textContent = opfsAvailable ? 'IndexedDB cache (OPFS available)' : 'IndexedDB cache';
    }
    if (clearButton) clearButton.disabled = entryCount === 0;
}

export async function initPdfContainers(root) {
    const scope = root || document;
    const blocks = scope.querySelectorAll('[data-pdf-block]');
    for (const block of blocks) {
        // Skip binding viewer-mode blocks with no filename yet (overlay hidden at page load)
        const container = block.querySelector('[data-pdf-container]');
        if (container?.hasAttribute('data-pdf-viewer-mode') &&
            !container.getAttribute('data-pdf-expected-filename')) continue;
        bindBlockControls(block);
    }

    // Viewer-mode containers: render if they have a filename (skip empty overlay at page load)
    // Card-mode containers: lazy-render via IntersectionObserver
    const observer = getCardObserver();
    for (const block of blocks) {
        const container = block.querySelector('[data-pdf-container]');
        if (!container) continue;
        if (container.hasAttribute('data-pdf-viewer-mode')) {
            if (container.getAttribute('data-pdf-expected-filename')) {
                await renderContainer(container);
            }
        } else if (!_pendingCards.has(block)) {
            _pendingCards.add(block);
            observer.observe(block);
        }
    }

    // Show browse buttons for any mapped PDFs (covers HTMX-loaded content)
    refreshBrowseButtons();
    await updateStorageUi();
}

export async function clearAllPdfMappings() {
    await idbClearMappings();
    mappingRegistry.clear();
    pdfDocumentCache.clear();
    document.dispatchEvent(new CustomEvent('pdf-mapped', {
        detail: { expectedFilename: null, expectedKey: null },
    }));
}
