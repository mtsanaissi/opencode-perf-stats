/* opencode-perf-stats web UI — selection basket + compare form toggle.
 * Vanilla JS, no dependencies. Persists selected session IDs in sessionStorage.
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

        // Row click toggles via the link; let checkbox handle its own state.
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

    // ── compare form: type toggle ─────────────────────────────────────────────
    var form = document.getElementById("compare-form");
    var typeSelect = document.getElementById("cmp-type");
    if (form && typeSelect) {
        typeSelect.addEventListener("change", toggleFields);
        toggleFields();

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var type = typeSelect.value;
            var raw;
            if (type === "sessions") raw = val("cmp-ids");
            else if (type === "models") raw = val("cmp-names");
            else raw = val("cmp-values");
            var items = raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
            if (items.length < 2) {
                alert("Enter at least 2 items to compare.");
                return;
            }
            var param = type === "sessions" ? "ids" : type === "models" ? "names" : "values";
            var path = type === "sessions" ? "/compare/sessions"
                     : type === "models" ? "/compare/models" : "/compare/days";
            window.location.href = path + "?" + param + "=" + encodeURIComponent(items.join(","));
        });
    }

    function toggleFields() {
        var t = typeSelect.value;
        show("field-ids", t === "sessions");
        show("field-names", t === "models");
        show("field-values", t === "days");
    }

    function show(id, on) {
        var el = document.getElementById(id);
        if (el) el.style.display = on ? "flex" : "none";
    }

    function val(id) {
        var el = document.getElementById(id);
        return el ? el.value : "";
    }
})();
