(() => {
  "use strict";

  const container = document.querySelector("[data-ticket-custom-fields]");
  if (!container) return;
  const payload = container.querySelector("[data-custom-fields-payload]");
  const rows = container.querySelector("[data-custom-field-rows]");
  const addButton = container.querySelector("[data-add-custom-field]");
  const errorMessage = container.querySelector("[data-custom-field-error]");
  const form = container.closest("form");

  /** DOM의 현재 값을 타입이 있는 ticket-local 필드 목록으로 직렬화한다. */
  function synchronizePayload() {
    const customFields = [];
    for (const row of rows.children) {
      const customField = {
        name: row.querySelector("[data-field-name]").value,
        field_type: row.querySelector("[data-field-type]").value,
        value: row.querySelector("[data-field-value]").value,
      };
      if (row.dataset.fieldId) customField.field_id = row.dataset.fieldId;
      customFields.push(customField);
    }
    payload.value = JSON.stringify(customFields);
    addButton.disabled = rows.children.length >= 30;
  }

  /** 사용자 문자열을 HTML로 해석하지 않고 label과 입력 도구를 생성한다. */
  function appendInput(row, title, input, attributeName) {
    const label = document.createElement("label");
    label.className = "field";
    const caption = document.createElement("span");
    caption.textContent = title;
    input.setAttribute(attributeName, "");
    label.append(caption, input);
    row.append(label);
    return input;
  }

  /** 저장된 ID를 유지하면서 Text 필드의 편집 행을 추가한다. */
  function appendField(customField = {}) {
    const row = document.createElement("div");
    row.className = "custom-field-row";
    if (customField.field_id) row.dataset.fieldId = customField.field_id;
    const nameInput = document.createElement("input");
    nameInput.value = customField.name || "";
    nameInput.maxLength = 100;
    nameInput.required = true;
    appendInput(row, "필드 이름", nameInput, "data-field-name");

    const typeInput = document.createElement("select");
    const textOption = document.createElement("option");
    textOption.value = "TEXT";
    textOption.textContent = "Text";
    typeInput.append(textOption);
    appendInput(row, "타입", typeInput, "data-field-type");

    const valueInput = document.createElement("textarea");
    valueInput.value = customField.value || "";
    valueInput.maxLength = 10000;
    valueInput.rows = 3;
    appendInput(row, "값", valueInput, "data-field-value");

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "button quiet";
    removeButton.textContent = "필드 제거";
    removeButton.addEventListener("click", () => {
      row.remove();
      synchronizePayload();
      addButton.focus();
    });
    row.append(removeButton);
    rows.append(row);
    return nameInput;
  }

  try {
    const savedFields = JSON.parse(payload.value);
    if (!Array.isArray(savedFields) || savedFields.length > 30) throw new Error("invalid fields");
    for (const customField of savedFields) {
      if (!customField || typeof customField.name !== "string" ||
          (customField.field_type !== undefined && customField.field_type !== "TEXT") ||
          (customField.value !== undefined && typeof customField.value !== "string")) {
        throw new Error("unsupported field");
      }
      appendField(customField);
    }
    addButton.disabled = rows.children.length >= 30;
  } catch {
    errorMessage.textContent = "추가 필드 입력을 복원하지 못했습니다. 원본 입력을 확인하거나 페이지를 다시 여세요.";
    errorMessage.hidden = false;
    payload.hidden = false;
    rows.replaceChildren();
    addButton.disabled = true;
    return;
  }

  addButton.addEventListener("click", () => {
    if (rows.children.length >= 30) return;
    const nameInput = appendField();
    synchronizePayload();
    nameInput.focus();
  });
  rows.addEventListener("input", synchronizePayload);
  rows.addEventListener("change", synchronizePayload);
  form.addEventListener("submit", synchronizePayload);
})();
