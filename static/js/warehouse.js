(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const translationsNode = document.getElementById("page-translations");
  const cabinetConfigNode = document.getElementById("warehouse-cabinet-config");
  const I18N = JSON.parse(translationsNode.textContent);
  let cabinets = JSON.parse(cabinetConfigNode.textContent);
  const cabinetSelect = document.getElementById("warehouse-cabinet-select");
  const summary = document.getElementById("warehouse-summary");
  const boxMeta = document.getElementById("warehouse-box-meta");
  const visual = document.getElementById("warehouse-cabinet-visual");
  const detailsPlaceholder = document.getElementById("warehouse-drawer-placeholder");
  const detailsContent = document.getElementById("warehouse-drawer-content");
  const printSheet = document.getElementById("warehouse-print-sheet");
  const drawerParts = document.getElementById("warehouse-drawer-parts");
  const drawerPartsEmpty = document.getElementById("warehouse-drawer-parts-empty");
  let unplacedPartCount = 0;
  let selectedDrawerNode = null;

  function translation(key) {
    return I18N[key] || key;
  }

  function makeSvgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    return element;
  }

  function formatDimensions(width, depth, height) {
    return `${width} × ${depth} × ${height} mm`;
  }

  function makeQrSvg(payload, label) {
    if (typeof window.qrcode !== "function") {
      throw new Error("The local QR code generator did not load.");
    }
    const qr = window.qrcode(0, "M");
    qr.addData(payload, "Byte");
    qr.make();
    const wrapper = document.createElement("div");
    wrapper.innerHTML = qr.createSvgTag(4, 4);
    const svg = wrapper.firstElementChild;
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
    return svg;
  }

  function setText(elementId, value) {
    document.getElementById(elementId).textContent = value;
  }

  function appendBoxMeta(label, value) {
    const item = document.createElement("span");
    const labelNode = document.createElement("strong");
    labelNode.textContent = `${label}: `;
    item.append(labelNode, document.createTextNode(value));
    boxMeta.appendChild(item);
  }

  function renderSummary(cabinet) {
    summary.replaceChildren();
    const items = [[translation("box_id"), cabinet.id]];
    for (const group of cabinet.drawerGroups) {
    items.push([drawerTypeName(group), String(group.drawers.length)]);
    }
    const registeredParts = cabinet.drawerGroups.flatMap(group => group.drawers)
      .reduce((count, drawer) => count + (drawer.parts || []).length, 0);
    items.push([translation("drawer_parts_count"), String(registeredParts)]);
    items.push([translation("unplaced_count"), String(unplacedPartCount)]);
    for (const [label, value] of items) {
      const item = document.createElement("span");
      item.className = "warehouse-summary-item";
      const strong = document.createElement("strong");
      strong.textContent = `${label}: `;
      item.append(strong, document.createTextNode(value));
      summary.appendChild(item);
    }
  }

  function renderBoxMeta(cabinet) {
    boxMeta.replaceChildren();
    appendBoxMeta(translation("cabinet_number"), String(cabinet.displayNumber));
    appendBoxMeta(translation("box_id"), cabinet.id);
    appendBoxMeta(
      translation("outer_dimensions"),
      formatDimensions(cabinet.widthMm, cabinet.depthMm, cabinet.heightMm),
    );
  }

  function drawerTypeName(group) {
    return translation(group.typeLabelKey || group.typeCode);
  }

  function renderDrawerDetails(cabinet, group, drawer, drawerNode) {
    detailsPlaceholder.hidden = true;
    detailsContent.hidden = false;
    setText("warehouse-detail-box", cabinet.id);
    setText("warehouse-detail-code", `${cabinet.displayNumber} / ${drawer.code}`);
    setText("warehouse-detail-type", drawerTypeName(group));
    setText(
      "warehouse-detail-dimensions",
      formatDimensions(drawer.widthMm, drawer.depthMm, drawer.heightMm),
    );
    const rowText = translation("drawer_row").replace("{row}", drawer.row);
    const columnText = translation("drawer_column").replace("{column}", drawer.column);
    setText("warehouse-detail-position", `${rowText}, ${columnText}`);
    renderDrawerParts(drawer);

    const qrContainer = document.getElementById("warehouse-selected-qr");
    qrContainer.replaceChildren(makeQrSvg(drawer.qrPayload, `${drawer.code} ${translation("qr_code")}`));
    setText("warehouse-selected-qr-payload", drawer.qrPayload);

    const visualLabel = `${cabinet.id} ${drawer.code}, ${drawerTypeName(group)}`;
    if (selectedDrawerNode) {
      selectedDrawerNode.classList.remove("is-selected");
      selectedDrawerNode.setAttribute("aria-pressed", "false");
    }
    selectedDrawerNode = drawerNode;
    if (selectedDrawerNode) {
      selectedDrawerNode.classList.add("is-selected");
      selectedDrawerNode.setAttribute("aria-pressed", "true");
      selectedDrawerNode.setAttribute("aria-label", visualLabel);
    }
  }

  function renderDrawerParts(drawer) {
    const parts = drawer.parts || [];
    drawerParts.replaceChildren();
    drawerPartsEmpty.hidden = parts.length > 0;
    for (const part of parts) {
      const card = document.createElement("article");
      card.className = "warehouse-part-card";
      const photo = document.createElement("img");
      photo.className = "warehouse-part-photo";
      photo.src = part.photo_url;
      photo.alt = part.name;
      const content = document.createElement("div");
      const name = document.createElement("a");
      name.href = `/component_details?part_id=${encodeURIComponent(part.id)}`;
      name.textContent = part.name;
      name.className = "fw-bold";
      const metadata = document.createElement("p");
      metadata.className = "text-muted mb-1";
      metadata.textContent = [part.library_source, part.external_part_id, part.package]
        .filter(Boolean).join(" · ");
      const quantity = document.createElement("span");
      quantity.textContent = `${translation("part_quantity")}: ${part.quantity}`;
      content.append(name, metadata, quantity);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-outline-danger btn-sm d-block mt-2";
      remove.dataset.removePartId = part.id;
      remove.textContent = translation("remove_part");
      content.appendChild(remove);
      card.append(photo, content);
      drawerParts.appendChild(card);
    }
  }

  function selectDrawer(cabinet, group, drawer, drawerNode) {
    renderDrawerDetails(cabinet, group, drawer, drawerNode);
  }

  function renderCabinet(cabinet) {
    selectedDrawerNode = null;
    detailsPlaceholder.hidden = false;
    detailsContent.hidden = true;
    renderSummary(cabinet);
    renderBoxMeta(cabinet);
    visual.replaceChildren();

    const svg = makeSvgElement("svg", {
      class: "warehouse-cabinet-svg",
      viewBox: `0 0 ${cabinet.widthMm} ${cabinet.heightMm}`,
      role: "group",
      "aria-label": `${cabinet.id}, ${formatDimensions(cabinet.widthMm, cabinet.depthMm, cabinet.heightMm)}`,
    });
    svg.appendChild(
      makeSvgElement("rect", {
        class: "warehouse-cabinet-outline",
        x: 1.5,
        y: 1.5,
        width: cabinet.widthMm - 3,
        height: cabinet.heightMm - 3,
        rx: 5,
      }),
    );

    for (const group of cabinet.drawerGroups) {
      for (const drawer of group.drawers) {
        const drawerGroup = makeSvgElement("g", {
          class: "warehouse-drawer",
          role: "button",
          tabindex: 0,
          "aria-pressed": "false",
          "aria-label": `${cabinet.id} ${drawer.code}, ${drawerTypeName(group)}`,
          "data-drawer-code": drawer.code,
        });
        drawerGroup.appendChild(
          makeSvgElement("rect", {
            class: "warehouse-drawer-face",
            x: drawer.xMm,
            y: drawer.yMm,
            width: drawer.widthMm,
            height: drawer.heightMm,
            rx: 1.2,
          }),
        );
        const label = makeSvgElement("text", {
          class: "warehouse-drawer-label",
          x: drawer.xMm + drawer.widthMm / 2,
          y: drawer.yMm + drawer.heightMm / 2,
          "font-size": Math.min(15, drawer.heightMm * 0.4, drawer.widthMm * 0.25),
        });
        label.textContent = drawer.code;
        drawerGroup.appendChild(label);

        const activate = () => selectDrawer(cabinet, group, drawer, drawerGroup);
        drawerGroup.addEventListener("click", activate);
        drawerGroup.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          }
        });
        svg.appendChild(drawerGroup);
      }
    }
    visual.appendChild(svg);
  }

  function addCabinetOptions() {
    for (const cabinet of cabinets) {
      const option = document.createElement("option");
      option.value = cabinet.id;
      option.textContent = `${cabinet.displayNumber} — ${cabinet.id}`;
      cabinetSelect.appendChild(option);
    }
  }

  async function loadWarehouseContents() {
    try {
      const response = await fetch("/api/warehouse/contents");
      if (!response.ok) throw new Error("warehouse contents request failed");
      const payload = await response.json();
      cabinets = payload.cabinets || [];
      unplacedPartCount = payload.unplaced_part_count || 0;
      const selectedCode = selectedDrawerNode && selectedDrawerNode.dataset.drawerCode;
      const selected = cabinets.find(item => item.id === cabinetSelect.value) || cabinets[0];
      if (selected) {
        cabinetSelect.value = selected.id;
        renderCabinet(selected);
        const node = Array.from(visual.querySelectorAll("[data-drawer-code]"))
          .find(item => item.dataset.drawerCode === selectedCode);
        if (node) node.dispatchEvent(new Event("click"));
      }
    } catch (error) {
      console.error(error);
      summary.textContent = translation("warehouse_load_error");
    }
  }

  function makeLabel(cabinet, group, drawer) {
    const label = document.createElement("article");
    label.className = "warehouse-label";
    const qrContainer = document.createElement("div");
    qrContainer.className = "warehouse-label-qr";
    qrContainer.appendChild(makeQrSvg(drawer.qrPayload, `${drawer.code} ${translation("qr_code")}`));

    const info = document.createElement("div");
    info.className = "warehouse-label-info";
    const humanCode = document.createElement("strong");
    humanCode.textContent = `${cabinet.displayNumber} / ${drawer.code}`;
    const cabinetCode = document.createElement("span");
    cabinetCode.textContent = cabinet.id;
    const drawerType = document.createElement("span");
    drawerType.textContent = drawerTypeName(group);
    info.append(humanCode, cabinetCode, drawerType);
    label.append(qrContainer, info);
    return label;
  }

  function preparePrintSheet(selectedCabinets) {
    printSheet.replaceChildren();
    const drawers = selectedCabinets.flatMap(cabinet => cabinet.drawerGroups.flatMap(group =>
      group.drawers.map(drawer => ({cabinet, group, drawer})),
    ));
    const labelsPerPage = 32;
    for (let offset = 0; offset < drawers.length; offset += labelsPerPage) {
      const page = document.createElement("section");
      page.className = "warehouse-label-page";
      page.setAttribute("aria-label", `${translation("print_labels")}, ${Math.floor(offset / labelsPerPage) + 1}`);
      for (const { cabinet, group, drawer } of drawers.slice(offset, offset + labelsPerPage)) {
        page.appendChild(makeLabel(cabinet, group, drawer));
      }
      printSheet.appendChild(page);
    }
  }

  addCabinetOptions();
  document.addEventListener("warehouse:refresh", loadWarehouseContents);
  document.addEventListener("warehouse:show-drawer", (event) => {
    if (!event.detail) return;
    const cabinet = cabinets.find(item => item.id === event.detail.cabinet_id);
    if (!cabinet) return;
    if (!cabinet.drawerGroups.some(group => group.drawers.some(drawer => drawer.code === event.detail.drawer_code))) return;
    cabinetSelect.value = cabinet.id;
    renderCabinet(cabinet);
    const node = Array.from(visual.querySelectorAll("[data-drawer-code]"))
      .find(item => item.dataset.drawerCode === event.detail.drawer_code);
    if (node) {
      node.dispatchEvent(new Event("click"));
      if (event.detail.scroll_to_drawer) {
        window.requestAnimationFrame(() => {
          const panel = document.getElementById("warehouse-drawer-details");
          panel.focus({preventScroll: true});
          panel.scrollIntoView({behavior: "smooth", block: "start"});
        });
      }
    }
  });
  cabinetSelect.addEventListener("change", () => {
    const cabinet = cabinets.find((item) => item.id === cabinetSelect.value);
    if (cabinet) {
      renderCabinet(cabinet);
    }
  });
  const printModalNode = document.getElementById("warehouse-print-modal");
  const printModal = bootstrap.Modal.getOrCreateInstance(printModalNode);
  const printCurrent = document.getElementById("warehouse-print-current");
  const printAll = document.getElementById("warehouse-print-all");
  const printConfirm = document.getElementById("warehouse-print-confirm");
  let printRequested = false;
  printModalNode.addEventListener("show.bs.modal", () => {
    printRequested = false;
    const cabinet = cabinets.find((item) => item.id === cabinetSelect.value);
    setText("warehouse-print-current-box", cabinet ? `(${cabinet.displayNumber} / ${cabinet.id})` : "");
    printCurrent.disabled = !cabinet;
    printCurrent.checked = !!cabinet;
    printAll.disabled = !cabinets.length;
    printAll.checked = !cabinet && !!cabinets.length;
    printConfirm.disabled = !cabinets.length;
  });
  document.getElementById("warehouse-print-form").addEventListener("submit", event => {
    event.preventDefault();
    if (printRequested) return;
    const cabinet = cabinets.find((item) => item.id === cabinetSelect.value);
    const selectedCabinets = printAll.checked ? cabinets : cabinet ? [cabinet] : [];
    if (!selectedCabinets.length) return;
    preparePrintSheet(selectedCabinets);
    printRequested = true;
    printConfirm.disabled = true;
    printModal.hide();
  });
  printModalNode.addEventListener("hidden.bs.modal", () => {
    if (!printRequested) return;
    printRequested = false;
    window.requestAnimationFrame(() => window.print());
  });

  if (cabinets.length > 0) {
    cabinetSelect.value = cabinets[0].id;
    renderCabinet(cabinets[0]);
  }
  loadWarehouseContents();
})();
