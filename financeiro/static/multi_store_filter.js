(() => {
  const supported = new Set(["/", "/dre", "/saude-financeira"]);
  if (!supported.has(window.location.pathname)) return;

  document.querySelectorAll('form.filters select[name="store"]').forEach((select) => {
    if (select.dataset.multiReady === "1") return;
    select.dataset.multiReady = "1";

    const params = new URLSearchParams(window.location.search);
    const selectedFromUrl = params.getAll("store").filter(Boolean);
    const stores = Array.from(select.options)
      .map((option) => option.value)
      .filter(Boolean);
    const selected = new Set(selectedFromUrl);

    const details = document.createElement("details");
    details.className = "multi-store-filter";
    details.style.minWidth = "230px";
    details.style.position = "relative";

    const summary = document.createElement("summary");
    summary.style.cursor = "pointer";
    summary.style.padding = "10px 12px";
    summary.style.border = "1px solid #d7d7d7";
    summary.style.borderRadius = "8px";
    summary.style.background = "#fff";

    const label = document.createElement("span");
    const refreshLabel = () => {
      const count = details.querySelectorAll('input[type="checkbox"]:checked').length;
      label.textContent = count === 0 ? "Todas as unidades" : count === 1 ? "1 unidade selecionada" : `${count} unidades selecionadas`;
    };
    summary.appendChild(label);
    details.appendChild(summary);

    const panel = document.createElement("div");
    panel.style.position = "absolute";
    panel.style.zIndex = "50";
    panel.style.top = "calc(100% + 6px)";
    panel.style.left = "0";
    panel.style.minWidth = "280px";
    panel.style.maxHeight = "320px";
    panel.style.overflowY = "auto";
    panel.style.padding = "10px";
    panel.style.border = "1px solid #d7d7d7";
    panel.style.borderRadius = "10px";
    panel.style.background = "#fff";
    panel.style.boxShadow = "0 8px 24px rgba(0,0,0,.12)";

    const actions = document.createElement("div");
    actions.style.display = "flex";
    actions.style.gap = "8px";
    actions.style.marginBottom = "8px";

    const allButton = document.createElement("button");
    allButton.type = "button";
    allButton.textContent = "Selecionar todas";
    allButton.className = "btn small";

    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.textContent = "Limpar";
    clearButton.className = "btn small";

    actions.append(allButton, clearButton);
    panel.appendChild(actions);

    const checkboxes = [];
    stores.forEach((store) => {
      const row = document.createElement("label");
      row.style.display = "flex";
      row.style.alignItems = "center";
      row.style.gap = "9px";
      row.style.padding = "8px 4px";
      row.style.cursor = "pointer";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "store";
      checkbox.value = store;
      checkbox.checked = selected.has(store);
      checkbox.addEventListener("change", refreshLabel);
      checkboxes.push(checkbox);

      const text = document.createElement("span");
      text.textContent = store;
      row.append(checkbox, text);
      panel.appendChild(row);
    });

    allButton.addEventListener("click", () => {
      checkboxes.forEach((cb) => { cb.checked = true; });
      refreshLabel();
    });
    clearButton.addEventListener("click", () => {
      checkboxes.forEach((cb) => { cb.checked = false; });
      refreshLabel();
    });

    details.appendChild(panel);
    select.disabled = true;
    select.style.display = "none";
    select.parentNode.insertBefore(details, select.nextSibling);
    refreshLabel();
  });
})();
