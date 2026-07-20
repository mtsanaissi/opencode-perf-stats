/* opencode-perf-stats web UI — selection basket, compare pickers, message table.
 * Vanilla JS, no dependencies. Persists compare pick selections in
 * sessionStorage (distinct keys per basket). No client-side fetch: pickers are
 * server-rendered; JS only wires up tab switching, sticky "Compare selected"
 * bars, and date-range preset/custom merging.
 *
 * Two modules:
 *   1. discovery selection basket + compare picker bars (always runs)
 *   2. per-message table pagination + accordion (only on #msg-table-wrap pages)
 */
(function () {
    "use strict";

    // ── discovery: selection basket ──────────────────────────────────────────
    var STORAGE_KEY = "opencode-perf-stats:compare-ids";
    var basket = document.getElementById("basket");
    var basketCount = document.getElementById("basket-count");
    var basketLink = document.getElementById("basket-link");
    var selectAll = document.getElementById("select-all");
    var checkboxes = Array.prototype.slice.call(document.querySelectorAll(".row-check"));

    if (checkboxes.length) {
        // Load prior selection (persisted across navigation).
        var saved = {};
        try { saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}"); } catch (e) {}
        checkboxes.forEach(function (cb) {
            cb.checked = !!saved[cb.value];
            cb.addEventListener("change", onCheckChange);
        });
        selectAll && selectAll.addEventListener("change", function () {
            checkboxes.forEach(function (cb) { cb.checked = selectAll.checked; });
            onCheckChange();
        });
        updateBasket();
    }

    function onCheckChange() {
        updateBasket();
        var saved = {};
        checkboxes.forEach(function (cb) { if (cb.checked) saved[cb.value] = true; });
        try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(saved)); } catch (e) {}
    }

    function updateBasket() {
        var selected = checkboxes.filter(function (cb) { return cb.checked; });
        if (!basket) return;
        if (selected.length) {
            basket.style.display = "flex";
            basketCount.textContent = selected.length;
            var ids = selected.map(function (cb) { return cb.value; }).join(",");
            basketLink.href = ids.length >= 2
                ? basketLink.getAttribute("data-base") + "?ids=" + encodeURIComponent(ids)
                : "#";
            basketLink.classList.toggle("btn-primary", ids.length >= 2);
            basketLink.style.opacity = ids.length >= 2 ? "1" : "0.5";
            basketLink.style.pointerEvents = ids.length >= 2 ? "auto" : "none";
        } else {
            basket.style.display = "none";
        }
    }

    // Wire the basket link base href (compare sessions route) once.
    if (basketLink && !basketLink.getAttribute("data-base")) {
        basketLink.setAttribute("data-base", basketLink.href);
    }

    // ── compare: type tabs ───────────────────────────────────────────────────
    var tabBtns = Array.prototype.slice.call(document.querySelectorAll(".tab-btn"));
    var panels = {
        sessions: document.getElementById("panel-sessions"),
        models: document.getElementById("panel-models"),
    };

    tabBtns.forEach(function (btn) {
        btn.addEventListener("click", function () {
            var type = btn.getAttribute("data-type");
            tabBtns.forEach(function (b) { b.classList.remove("active"); });
            btn.classList.add("active");
            Object.keys(panels).forEach(function (k) {
                if (panels[k]) panels[k].style.display = k === type ? "" : "none";
            });
        });
    });

    // ── compare: generic checkbox basket (sessions & models) ─────────────────
    // Pickers are server-rendered with active selection pre-checked. JS merges
    // any sessionStorage-persisted selection, updates the sticky "Compare
    // selected" bar, and builds the comparison URL.
    function setupBasket(opts) {
        var checks = Array.prototype.slice.call(
            document.querySelectorAll('input.cmp-check[data-basket="' + opts.basket + '"]')
        );
        if (!checks.length) return;

        var bar = document.getElementById(opts.barId);
        var countEl = document.getElementById(opts.countId);
        var link = document.getElementById(opts.linkId);

        var saved = {};
        try { saved = JSON.parse(sessionStorage.getItem(opts.storageKey) || "{}"); } catch (e) {}

        checks.forEach(function (cb) {
            // Merge persisted selection onto the server-rendered (active) state.
            if (saved[cb.value]) cb.checked = true;
            cb.addEventListener("change", function () {
                persist();
                update();
            });
        });

        function persist() {
            var s = {};
            checks.forEach(function (cb) { if (cb.checked) s[cb.value] = true; });
            try { sessionStorage.setItem(opts.storageKey, JSON.stringify(s)); } catch (e) {}
        }

        function update() {
            var sel = checks.filter(function (cb) { return cb.checked; });
            var n = sel.length;
            if (countEl) countEl.textContent = n;
            if (bar) bar.style.display = n > 0 ? "flex" : "none";
            if (link) {
                var ok = n >= opts.min;
                link.classList.toggle("btn-primary", ok);
                link.style.opacity = ok ? "1" : "0.5";
                link.style.pointerEvents = ok ? "auto" : "none";
                if (ok) {
                    var vals = sel.map(function (cb) { return cb.value; }).join(",");
                    link.href = link.getAttribute("data-base") + "?" + opts.param + "=" + encodeURIComponent(vals);
                } else {
                    link.href = "#";
                }
            }
        }

        update();
    }

    setupBasket({
        basket: "sessions",
        barId: "session-bar",
        countId: "session-count",
        linkId: "compare-sessions-btn",
        param: "ids",
        min: 2,
        storageKey: "opencode-perf-stats:cmp-sessions",
    });
    setupBasket({
        basket: "models",
        barId: "model-bar",
        countId: "model-count",
        linkId: "compare-models-btn",
        param: "names",
        min: 2,
        storageKey: "opencode-perf-stats:cmp-models",
    });
})();

/* ── 2nd module: per-message table pagination + accordion rows ────────────
 * Activates only when #msg-table-wrap is present (single.html report page).
 * Pagination is purely client-side: all rows exist in DOM, we show/hide.
 * Accordion: clicking a .msg-data-row toggles its sibling .msg-detail-row.
 */
(function () {
    "use strict";

    var wrap = document.getElementById("msg-table-wrap");
    if (!wrap) return; // not the session report page

    var tbody = document.getElementById("msg-tbody");
    var pageNumTop = document.getElementById("page-num-top");
    var pageTotalTop = document.getElementById("page-total-top");
    var pageNumBottom = document.getElementById("page-num-bottom");
    var pageTotalBottom = document.getElementById("page-total-bottom");
    var prevBtn = document.getElementById("prev-page");
    var nextBtn = document.getElementById("next-page");
    var prevBtnBottom = document.getElementById("prev-page-bottom");
    var nextBtnBottom = document.getElementById("next-page-bottom");
    var perPage = document.getElementById("per-page");
    var perPageBottom = document.getElementById("per-page-bottom");

    // ── collect rows ──────────────────────────────────────────────────────
    var allRows = Array.prototype.slice.call(tbody.querySelectorAll(".msg-data-row"));

    function totalPages(nRows, pp) {
        return Math.max(1, Math.ceil(nRows / pp));
    }

    function updatePagination(page, pp) {
        var total = totalPages(allRows.length, pp);
        // Clamp
        if (page < 1) page = 1;
        if (page > total) page = total;

        var start = (page - 1) * pp;
        var end = Math.min(start + pp, allRows.length);

        // Show/hide data rows
        allRows.forEach(function (row, i) {
            var visible = i >= start && i < end;
            row.style.display = visible ? "" : "none";
            // Hide its detail row when the data row is hidden
            var detail = document.getElementById("msg-detail-" + (i + 1));
            if (detail && !visible) {
                detail.hidden = true;
                row.setAttribute("aria-expanded", "false");
            }
        });

        // Update page numbers
        var text = "" + page;
        pageNumTop.textContent = text;
        pageNumBottom.textContent = text;
        text = "" + total;
        pageTotalTop.textContent = text;
        pageTotalBottom.textContent = text;

        // Prev/next state
        var atFirst = page <= 1;
        var atLast = page >= total;
        prevBtn.disabled = atFirst;
        nextBtn.disabled = atLast;
        prevBtnBottom.disabled = atFirst;
        nextBtnBottom.disabled = atLast;

        return page;
    }

    // ── synchronise the two per-page selects ──────────────────────────────
    function syncPerPage(from, to) {
        if (from.value !== to.value) {
            to.value = from.value;
        }
    }

    function onPerPageChange() {
        syncPerPage(perPage, perPageBottom);
        syncPerPage(perPageBottom, perPage);
        currentPage = updatePagination(1, parseInt(perPage.value, 10));
    }

    perPage.addEventListener("change", onPerPageChange);
    perPageBottom.addEventListener("change", onPerPageChange);

    // ── prev/next ─────────────────────────────────────────────────────────
    function onPrev() {
        var pp = parseInt(perPage.value, 10);
        currentPage = updatePagination(currentPage - 1, pp);
    }
    function onNext() {
        var pp = parseInt(perPage.value, 10);
        currentPage = updatePagination(currentPage + 1, pp);
    }

    prevBtn.addEventListener("click", onPrev);
    nextBtn.addEventListener("click", onNext);
    prevBtnBottom.addEventListener("click", onPrev);
    nextBtnBottom.addEventListener("click", onNext);

    // ── keyboard on prev/next buttons (already natively <button>) ─────────

    // ── accordion: row click toggle ───────────────────────────────────────
    function toggleRow(row) {
        // The detail row is the <tr> immediately following this data row.
        var detail = row.nextElementSibling;
        if (!detail || !detail.classList.contains("msg-detail-row")) return;

        var expanded = row.getAttribute("aria-expanded") === "true";
        if (expanded) {
            detail.hidden = true;
            row.setAttribute("aria-expanded", "false");
        } else {
            detail.hidden = false;
            row.setAttribute("aria-expanded", "true");
        }
    }

    function onRowClick(e) {
        // Don't toggle if user clicked a link or button inside the row
        if (e.target.closest("a, button, select, input, label")) return;
        toggleRow(this);
    }

    function onRowKeydown(e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggleRow(this);
        }
    }

    allRows.forEach(function (row) {
        row.addEventListener("click", onRowClick);
        row.addEventListener("keydown", onRowKeydown);
    });

    // ── initialize ────────────────────────────────────────────────────────
    var currentPage = 1;
    var defaultPP = parseInt(perPage.value, 10);
    currentPage = updatePagination(currentPage, defaultPP);
})();

/* ── 3rd module: message-content modal ────────────────────────────────
 * Activates only when #msg-table-wrap with data-session-id is present
 * (single.html report page). Creates a shared modal overlay on first
 * use and lazy-fetches message parts via the session-scoped API.
 */
(function () {
    "use strict";

    var wrap = document.getElementById("msg-table-wrap");
    if (!wrap || !wrap.getAttribute("data-session-id")) return;

    var sessionId = wrap.getAttribute("data-session-id");
    var modal = null;

    function ensureModal() {
        if (modal) return modal;
        modal = document.createElement("div");
        modal.className = "modal-overlay";
        modal.hidden = true;
        modal.innerHTML =
            '<div class="modal-content">' +
                '<button class="modal-close" aria-label="Close">&times;</button>' +
                '<div class="modal-header"></div>' +
                '<div class="modal-body"></div>' +
            '</div>';
        document.body.appendChild(modal);
        modal.addEventListener("click", function (e) {
            if (e.target === modal) closeModal();
        });
        modal.querySelector(".modal-close").addEventListener("click", closeModal);
        return modal;
    }

    function openModal(messageId) {
        ensureModal();
        var body = modal.querySelector(".modal-body");
        var header = modal.querySelector(".modal-header");
        body.innerHTML = '<div class="loading">Loading message content…</div>';
        header.innerHTML = '';
        modal.hidden = false;
        document.body.style.overflow = "hidden";

        // Look up message metadata from the embedded REPORT data.
        var meta = null;
        if (typeof REPORT !== "undefined" && REPORT.all_messages) {
            for (var i = 0; i < REPORT.all_messages.length; i++) {
                if (REPORT.all_messages[i].message_id === messageId) {
                    meta = REPORT.all_messages[i];
                    break;
                }
            }
        }

        var url = "/session/" + encodeURIComponent(sessionId) +
                  "/message/" + encodeURIComponent(messageId) + "/parts";
        fetch(url)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(function (data) {
                renderParts(body, data.parts || [], meta);
            })
            .catch(function (err) {
                body.innerHTML =
                    '<div class="modal-error">' +
                    '<p>Failed to load message content.</p>' +
                    '<p class="mono">' + err.message + '</p>' +
                    '</div>';
            });
    }

    function closeModal() {
        if (!modal) return;
        modal.hidden = true;
        document.body.style.overflow = "";
    }

    function renderParts(container, parts, meta) {
        var html = "";

        // Render message context metadata if available (user messages).
        if (meta && meta.role === "user") {
            html += '<div class="modal-metadata">';
            html += '<div class="modal-metadata-title">Message Context</div>';
            html += '<div class="modal-metadata-grid">';
            html += '<div class="modal-metadata-item"><span class="modal-metadata-label">Role</span>';
            html += '<span class="modal-metadata-value"><span class="badge badge-blue">User</span></span></div>';
            if (meta.agent) {
                html += '<div class="modal-metadata-item"><span class="modal-metadata-label">Agent</span>';
                html += '<span class="modal-metadata-value">' + escapeHtml(meta.agent) + '</span></div>';
            }
            if (meta.model_id) {
                var modelStr = (meta.provider_id || "") + "/" + meta.model_id;
                if (meta.variant) modelStr += " (" + meta.variant + ")";
                html += '<div class="modal-metadata-item"><span class="modal-metadata-label">Model</span>';
                html += '<span class="modal-metadata-value mono">' + escapeHtml(modelStr) + '</span></div>';
            }
            if (meta.created_ms) {
                html += '<div class="modal-metadata-item"><span class="modal-metadata-label">Created</span>';
                html += '<span class="modal-metadata-value mono">' + escapeHtml(formatTs(meta.created_ms)) + '</span></div>';
            }
            html += '</div></div>';
        }

        if (!parts.length) {
            if (!html) container.innerHTML = '<p class="modal-empty">No content parts found.</p>';
            else container.innerHTML = html;
            return;
        }
        parts.forEach(function (part, i) {
            var label = "";
            var content = "";
            if (part.type === "text") {
                label = "Text";
                content = '<pre class="modal-part-text">' + escapeHtml(part.text || "") + '</pre>';
            } else if (part.type === "reasoning") {
                label = "Reasoning";
                content = '<details class="modal-part-reasoning"><summary>Show reasoning</summary>' +
                           '<pre>' + escapeHtml(part.text || "") + '</pre></details>';
            } else if (part.type === "tool-call") {
                label = "Tool call: " + (part.name || "unknown");
                content = '<pre class="modal-part-tool">' + escapeHtml(formatToolInput(part)) + '</pre>';
            } else if (part.type === "tool-result") {
                label = "Tool result: " + (part.name || "unknown");
                content = '<pre class="modal-part-tool">' + escapeHtml(part.output || "") + '</pre>';
            } else {
                label = part.type;
                content = '<pre class="modal-part-unknown">' + escapeHtml(part.raw || "") + '</pre>';
            }
            var copyId = "modal-copy-" + i;
            html += '<div class="modal-part">' +
                        '<div class="modal-part-header">' +
                            '<span class="modal-part-label">' + escapeHtml(label) + '</span>' +
                            '<button class="btn btn-secondary modal-copy-btn" data-target="' + copyId + '" type="button">Copy</button>' +
                        '</div>' +
                        '<div id="' + copyId + '" class="modal-part-content">' + content + '</div>' +
                    '</div>';
        });
        container.innerHTML = html;

        // Wire copy buttons.
        container.querySelectorAll(".modal-copy-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var target = document.getElementById(btn.getAttribute("data-target"));
                if (!target) return;
                var text = target.textContent || "";
                navigator.clipboard.writeText(text).then(function () {
                    btn.textContent = "Copied!";
                    setTimeout(function () { btn.textContent = "Copy"; }, 1500);
                }).catch(function () {});
            });
        });
    }

    function formatToolInput(part) {
        var name = part.name || "";
        var input = part.input || "";
        if (typeof input === "object") {
            try { input = JSON.stringify(input, null, 2); } catch (e) {}
        }
        return name ? (name + "\n" + input) : input;
    }

    function formatTs(ms) {
        if (!ms) return "\u2014";
        var d = new Date(ms);
        var pad = function(n) { return n < 10 ? "0" + n : "" + n; };
        return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()) +
               " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + ":" + pad(d.getUTCSeconds()) + " UTC";
    }

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // Delegate click on .msg-content-btn.
    wrap.addEventListener("click", function (e) {
        var btn = e.target.closest(".msg-content-btn");
        if (!btn) return;
        e.stopPropagation();
        var messageId = btn.getAttribute("data-message-id");
        if (messageId) openModal(messageId);
    });

    // Escape key closes modal.
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && modal && !modal.hidden) {
            closeModal();
        }
    });
})();
