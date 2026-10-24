(function () {
  // Product filtering on /products/
  var grid = document.getElementById("grid");
  if (grid) {
    var PAGE = 48;
    var cards = [].slice.call(grid.querySelectorAll(".card"));
    var chips = [].slice.call(document.querySelectorAll("#filters .chip"));
    var q = document.getElementById("q");
    var none = document.getElementById("none");
    var more = document.getElementById("more");
    var cat = "all", limit = PAGE;
    var apply = function () {
      var term = q.value.trim().toLowerCase();
      var matches = cards.filter(function (c) {
        return (cat === "all" || c.dataset.cat === cat) &&
          (!term || (c.textContent + " " + (c.dataset.search || "")).toLowerCase().indexOf(term) > -1);
      });
      cards.forEach(function (c) { c.hidden = true; });
      matches.slice(0, limit).forEach(function (c) { c.hidden = false; });
      none.hidden = matches.length > 0;
      more.hidden = matches.length <= limit;
      more.textContent = "Show more (" + (matches.length - limit) + " left)";
    };
    var reset = function () { limit = PAGE; apply(); };
    chips.forEach(function (b) {
      b.addEventListener("click", function () {
        chips.forEach(function (x) { x.classList.remove("is-on"); });
        b.classList.add("is-on");
        cat = b.dataset.cat;
        reset();
      });
    });
    q.addEventListener("input", reset);
    more.addEventListener("click", function () { limit += PAGE; apply(); });
    apply();
  }

  // Category pages: filter by type (e.g. carpet: nylon, wool, tiles)
  var subs = document.getElementById("subfilters");
  if (subs) {
    var items = [].slice.call(document.querySelectorAll(".grid .card"));
    var sbtn = [].slice.call(subs.querySelectorAll(".chip"));
    sbtn.forEach(function (b) {
      b.addEventListener("click", function () {
        sbtn.forEach(function (x) { x.classList.remove("is-on"); });
        b.classList.add("is-on");
        items.forEach(function (c) { c.hidden = b.dataset.sub !== "all" && c.dataset.sub !== b.dataset.sub; });
      });
    });
  }

  // Prefill the quote form from ?product=
  var field = document.getElementById("product");
  if (field) {
    var p = new URLSearchParams(location.search).get("product");
    if (p) field.value = p;
  }

  // Navigation: Flooring dropdown (click/tap) and mobile menu
  var group = document.querySelector(".nav__group");
  var navBtn = document.querySelector(".nav__btn");
  var nav = document.getElementById("nav");
  var burger = document.querySelector(".burger");
  if (group && navBtn) {
    var setOpen = function (open) {
      group.classList.toggle("is-open", open);
      navBtn.setAttribute("aria-expanded", open ? "true" : "false");
    };
    navBtn.addEventListener("click", function () { setOpen(!group.classList.contains("is-open")); });
    document.addEventListener("click", function (e) {
      if (!group.contains(e.target)) setOpen(false);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
  }
  if (burger && nav) {
    burger.addEventListener("click", function () {
      var open = !nav.classList.contains("is-open");
      nav.classList.toggle("is-open", open);
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Small source photos are shown at their own size rather than stretched
  var hero = document.getElementById("pdp-img");
  if (hero) {
    var note = document.getElementById("swatch-note");
    var fit = function () {
      var low = hero.naturalWidth > 0 && hero.naturalWidth < 640;
      hero.parentNode.classList.toggle("is-lowres", low);
      if (note) note.hidden = !low;
    };
    hero.addEventListener("load", fit);
    if (hero.complete) fit();
  }

  // Product page colour picker
  var colours = document.getElementById("colours");
  if (colours) {
    var big = document.getElementById("pdp-img");
    var label = document.getElementById("colour-name");
    var csp = document.getElementById("colour-specs");
    var quote = document.getElementById("quote-btn");
    var swatches = [].slice.call(colours.querySelectorAll(".sw"));

    swatches.forEach(function (b) {
      b.addEventListener("click", function () {
        swatches.forEach(function (x) { x.classList.remove("is-on"); x.setAttribute("aria-pressed", "false"); });
        b.classList.add("is-on");
        b.setAttribute("aria-pressed", "true");
        var name = b.dataset.name;
        label.textContent = name;
        if (b.dataset.img && big) { big.src = b.dataset.img; big.alt = name; }
        if (csp) {
          var sp = {};
          try { sp = JSON.parse(b.dataset.specs || "{}"); } catch (e) {}
          csp.textContent = "";
          Object.keys(sp).forEach(function (k) {
            var row = document.createElement("div");
            var dt = document.createElement("dt"); dt.textContent = k;
            var dd = document.createElement("dd"); dd.textContent = sp[k];
            row.appendChild(dt); row.appendChild(dd); csp.appendChild(row);
          });
          csp.hidden = !Object.keys(sp).length;
        }
        if (quote) {
          var u = new URL(quote.getAttribute("href"), location.href);
          u.searchParams.set("product", quote.dataset.product + " - " + name);
          quote.setAttribute("href", u.pathname + u.search);
        }
      });
    });
  }
})();
