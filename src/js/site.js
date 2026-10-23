(function () {
  // Product filtering on /products/
  var grid = document.getElementById("grid");
  if (grid) {
    var PAGE = 48;
    var cards = [].slice.call(grid.querySelectorAll(".card"));
    var chips = [].slice.call(document.querySelectorAll("#filters .chip"));
    var q = document.getElementById("q");
    var brand = document.getElementById("brand");
    var none = document.getElementById("none");
    var more = document.getElementById("more");
    var cat = "all", limit = PAGE;
    var apply = function () {
      var term = q.value.trim().toLowerCase();
      var matches = cards.filter(function (c) {
        return (cat === "all" || c.dataset.cat === cat) &&
          (!brand.value || c.dataset.brand === brand.value) &&
          (!term || c.textContent.toLowerCase().indexOf(term) > -1);
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
    brand.addEventListener("change", reset);
    more.addEventListener("click", function () { limit += PAGE; apply(); });
    apply();
  }

  // Prefill the quote form from ?product=
  var field = document.getElementById("product");
  if (field) {
    var p = new URLSearchParams(location.search).get("product");
    if (p) field.value = p;
  }
})();
