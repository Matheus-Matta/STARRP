(function () {
  "use strict";

  var body = document.body;
  var collapseKey = "starrp.admin.sidebar-collapsed";
  var filter = document.getElementById("starrp-nav-filter");

  function readCollapsed() {
    try {
      return window.localStorage.getItem(collapseKey) === "1";
    } catch (error) {
      return false;
    }
  }

  function saveCollapsed(value) {
    try {
      window.localStorage.setItem(collapseKey, value ? "1" : "0");
    } catch (error) {
      /* A preferência permanece apenas nesta aba quando o storage está bloqueado. */
    }
  }

  if (readCollapsed() && window.matchMedia("(min-width: 901px)").matches) {
    body.classList.add("starrp-sidebar-collapsed");
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-admin-action]");
    if (!trigger) return;

    var action = trigger.getAttribute("data-admin-action");
    if (action === "collapse") {
      var collapsed = body.classList.toggle("starrp-sidebar-collapsed");
      saveCollapsed(collapsed);
    } else if (action === "open") {
      body.classList.add("starrp-sidebar-open");
    } else if (action === "close") {
      body.classList.remove("starrp-sidebar-open");
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") body.classList.remove("starrp-sidebar-open");
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && filter) {
      event.preventDefault();
      if (window.matchMedia("(max-width: 900px)").matches) {
        body.classList.add("starrp-sidebar-open");
      } else if (body.classList.contains("starrp-sidebar-collapsed")) {
        body.classList.remove("starrp-sidebar-collapsed");
        saveCollapsed(false);
      }
      filter.focus();
      filter.select();
    }
  });

  if (filter) {
    filter.addEventListener("input", function () {
      var query = filter.value.trim().toLocaleLowerCase("pt-BR");
      var visible = 0;

      document.querySelectorAll("[data-nav-item]").forEach(function (item) {
        var match = !query || item.textContent.toLocaleLowerCase("pt-BR").includes(query);
        item.hidden = !match;
        if (match) visible += 1;
      });

      document.querySelectorAll("[data-nav-group]").forEach(function (group) {
        var hasVisibleItem = Array.prototype.some.call(group.querySelectorAll("[data-nav-item]"), function (item) {
          return !item.hidden;
        });
        group.hidden = !hasVisibleItem;
      });

      var empty = document.querySelector(".starrp-nav-empty");
      if (empty) empty.hidden = visible !== 0;
    });
  }

  document.querySelectorAll(".starrp-nav-link.is-active, .starrp-nav-home.is-active").forEach(function (item) {
    item.setAttribute("aria-current", "page");
  });
})();
