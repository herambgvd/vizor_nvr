function syncSubfeatures() {
  const frs = document.querySelector('input[data-module="frs"]');
  const panel = document.querySelector('[data-subfeatures-for="frs"]');
  if (!frs || !panel) return;
  panel.style.display = frs.checked ? "block" : "none";
  panel.querySelectorAll("input").forEach((input) => {
    input.disabled = !frs.checked;
  });
}

document.addEventListener("change", (event) => {
  if (event.target && event.target.matches('input[data-module="frs"]')) {
    syncSubfeatures();
  }
});

document.addEventListener("DOMContentLoaded", syncSubfeatures);
