(function () {
  "use strict";

  var filter = document.querySelector("[data-menu-filter-mirror]");
  var items = Array.prototype.slice.call(document.querySelectorAll("[data-menu-item]"));
  var sections = Array.prototype.slice.call(document.querySelectorAll("[data-menu-section]"));
  var empty = document.querySelector(".menu-empty");

  function normalize(value) {
    return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
  }

  function filterMenu(value) {
    var query = normalize(value.trim());
    var visible = 0;

    items.forEach(function (item) {
      var matches = !query || normalize(item.textContent).includes(query);
      item.hidden = !matches;
      if (matches) visible += 1;
    });

    sections.forEach(function (section) {
      section.hidden = !Array.prototype.some.call(section.querySelectorAll("[data-menu-item]"), function (item) {
        return !item.hidden;
      });
    });

    if (empty) empty.hidden = visible !== 0;
  }

  if (filter) filter.addEventListener("input", function () { filterMenu(filter.value); });

  document.querySelectorAll(".menu-link.active").forEach(function (item) {
    item.setAttribute("aria-current", "page");
  });

  document.querySelectorAll(".sidebar-menu .menu-link").forEach(function (item) {
    item.addEventListener("click", function () { document.body.classList.remove("sidebar-open"); });
  });

  var changeForm = document.querySelector(".change-form #content-main > form");
  if (changeForm) {
    var dirty = false;
    var saveState = document.querySelector("[data-form-save-state]");

    function markDirty(event) {
      if (event && event.target && event.target.matches("[data-form-ignore-dirty]")) return;
      dirty = true;
      document.body.classList.add("form-dirty");
      if (saveState) saveState.hidden = false;
    }

    changeForm.addEventListener("input", markDirty);
    changeForm.addEventListener("change", markDirty);
    changeForm.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (event) {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
    document.addEventListener("keydown", function (event) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
      var save = changeForm.querySelector('button[name="_save"], input[name="_save"]');
      if (!save || save.disabled) return;
      event.preventDefault();
      changeForm.requestSubmit(save);
    });

    changeForm.querySelectorAll("fieldset.collapse > details").forEach(function (details) {
      var key = "starrp:admin:section:" + window.location.pathname + ":" + details.parentElement.id;
      var saved = window.sessionStorage.getItem(key);
      if (saved !== null) details.open = saved === "1";
      details.addEventListener("toggle", function () {
        window.sessionStorage.setItem(key, details.open ? "1" : "0");
      });
    });

    var firstError = changeForm.querySelector(".errors input, .errors select, .errors textarea, [aria-invalid='true']");
    if (firstError) firstError.focus({ preventScroll: true });
  }
})();
