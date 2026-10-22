(function () {
  // Product filtering on /products/
  var grid = document.getElementById("grid");
  if (grid) {
    var cards = [].slice.call(grid.querySelectorAll(".card"));
    var chips = [].slice.call(document.querySelectorAll("#filters .chip"));
    var q = document.getElementById("q");
    var none = document.getElementById("none");
    var cat = "all";
    var apply = function () {
      var term = q.value.trim().toLowerCase();
      var shown = 0;
      cards.forEach(function (c) {
        var ok = (cat === "all" || c.dataset.cat === cat) &&
          (!term || c.textContent.toLowerCase().indexOf(term) > -1);
        c.hidden = !ok;
        if (ok) shown++;
      });
      none.hidden = shown > 0;
    };
    chips.forEach(function (b) {
      b.addEventListener("click", function () {
        chips.forEach(function (x) { x.classList.remove("is-on"); });
        b.classList.add("is-on");
        cat = b.dataset.cat;
        apply();
      });
    });
    q.addEventListener("input", apply);
  }

  // Prefill the quote form from ?product=
  var field = document.getElementById("product");
  if (field) {
    var p = new URLSearchParams(location.search).get("product");
    if (p) field.value = p;
  }
})();
