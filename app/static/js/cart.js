document.addEventListener("DOMContentLoaded", function () {
  var variantInputs = document.querySelectorAll('input[name="variant_id"]');
  var secondFlavorField = document.getElementById("second-flavor-field");

  function updateSecondFlavorVisibility() {
    if (!secondFlavorField) return;
    var checked = document.querySelector('input[name="variant_id"]:checked');
    var maxFlavors = checked ? parseInt(checked.dataset.maxFlavors || "1", 10) : 1;
    secondFlavorField.style.display = maxFlavors > 1 ? "block" : "none";
    if (maxFlavors <= 1) {
      var select = secondFlavorField.querySelector("select");
      if (select) select.value = "";
    }
  }

  variantInputs.forEach(function (input) {
    input.addEventListener("change", updateSecondFlavorVisibility);
  });
  updateSecondFlavorVisibility();
});
