/** 필드별 입력과 조건 그룹을 하나의 v2 편집기에서 관리한다. */
function initializeTicketFilterEditor(editorForm) {
  const appliedDefinition = JSON.parse(editorForm.querySelector("[data-filter-definition]").textContent);
  const filterOptions = JSON.parse(editorForm.querySelector("[data-filter-options]").textContent);
  const editingDefinition = structuredClone(appliedDefinition);
  const expressionContainer = editorForm.querySelector("[data-filter-expression]");
  const summaryControl = editorForm.querySelector("[data-filter-summary]");
  const dirtyControl = editorForm.querySelector("[data-filter-dirty]");
  const errorControl = editorForm.querySelector("[data-filter-error]");
  let controlNumber = 0;
  const fieldDefinitions = {
    search: { label: "키·제목 검색", type: "text", operators: [["contains", "포함"], ["not_contains", "포함하지 않음"]] },
    type: { label: "유형", type: "choice", choices: [["EPIC", "Epic"], ["TASK", "Task"], ["SUBTASK", "Subtask"]] },
    status: { label: "상태", type: "choice", choices: [["TODO", "등록"], ["IN_PROGRESS", "진행중"], ["ON_HOLD", "보류"], ["DONE", "완료"], ["CANCELLED", "취소"]] },
    priority: { label: "중요도", type: "choice", choices: ["TRIVIAL", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"].map(value => [value, value]) },
    creator: { label: "생성자", type: "user" },
    assignee: { label: "담당자", type: "user", emptyLabel: "미지정" },
    epic: { label: "Epic 및 하위", type: "hierarchy" },
    parent: { label: "직접 상위", type: "hierarchy", emptyLabel: "상위 없음" },
    created_date: { label: "생성일", type: "date" },
    updated_date: { label: "수정일", type: "date" },
    due_date: { label: "마감일", type: "date", emptyLabel: "미설정" },
  };

  /** 사용자 입력을 HTML로 해석하지 않는 DOM 요소를 생성한다. */
  function createElement(tagName, className = "", textContent = "") {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = textContent;
    return element;
  }

  /** 연관 label과 고유 ID를 붙여 keyboard와 접근성 탐색을 지원한다. */
  function labelControl(labelText, control) {
    control.id = `ticket-filter-control-${++controlNumber}`;
    const label = createElement("label", "", labelText);
    label.htmlFor = control.id;
    label.append(control);
    return label;
  }

  /** 값·표시 이름 쌍으로 select를 생성한다. */
  function createSelect(choices, selectedValue) {
    const selectControl = createElement("select");
    for (const [choiceValue, choiceLabel] of choices) {
      const option = createElement("option", "", choiceLabel);
      option.value = String(choiceValue);
      option.selected = String(choiceValue) === String(selectedValue);
      selectControl.append(option);
    }
    return selectControl;
  }

  /** 필드가 허용하는 연산자만 표시한다. */
  function conditionOperators(fieldName) {
    const definition = fieldDefinitions[fieldName];
    let operators = definition.operators;
    if (!operators) {
      operators = definition.type === "date"
        ? [["on", "해당 날짜"], ["before", "이전 (선택일 제외)"], ["after", "이후 (선택일 제외)"], ["between", "기간 내 (양 끝 날짜 포함)"]]
        : [["in", "다음 중 하나"], ["not_in", "다음 중 하나가 아님"]];
    }
    if (definition.emptyLabel) {
      operators = [...operators, ["is_empty", definition.emptyLabel], ["is_not_empty", `${definition.emptyLabel} 아님`]];
    }
    return operators;
  }

  /** 프로젝트 후보에서 복수 선택 가능한 표시 값을 구성한다. */
  function conditionChoices(fieldName) {
    const definition = fieldDefinitions[fieldName];
    if (definition.type === "user") {
      return filterOptions.users.map(user => [user.id, `${user.display_name} · ${user.login_id}`]);
    }
    if (definition.type === "hierarchy") {
      const candidates = filterOptions.hierarchy.filter(ticket => fieldName !== "epic" || ticket.type === "EPIC");
      return candidates.map(ticket => [ticket.id, `${ticket.key} · ${ticket.title}`]);
    }
    return definition.choices;
  }

  /** 조건을 괄호가 포함된 읽기 전용 설명으로 변환한다. */
  function describeNode(conditionNode) {
    if (conditionNode.kind === "group") {
      const childDescriptions = conditionNode.children.map(describeNode);
      const description = childDescriptions.length ? `(${childDescriptions.join(` ${conditionNode.operator} `)})` : "전체 티켓";
      return conditionNode.negated ? `NOT ${description}` : description;
    }
    const definition = fieldDefinitions[conditionNode.field];
    const operatorLabel = conditionOperators(conditionNode.field).find(choice => choice[0] === conditionNode.operator)[1];
    let valueLabels = conditionNode.values;
    if (!["text", "date"].includes(definition.type)) {
      const choices = conditionChoices(conditionNode.field);
      valueLabels = conditionNode.values.map(value => choices.find(choice => choice[0] === value)?.[1] || String(value));
    }
    const description = `${definition.label} ${operatorLabel}${valueLabels.length ? ` [${valueLabels.join(", ")}]` : ""}`;
    return conditionNode.negated ? `NOT (${description})` : description;
  }

  /** 편집 내용과 적용된 내용을 구분하고 조건 요약을 갱신한다. */
  function synchronizeEditingState() {
    errorControl.hidden = true;
    summaryControl.textContent = describeNode(editingDefinition.expression);
    const isDirty = JSON.stringify(editingDefinition) !== JSON.stringify(appliedDefinition);
    dirtyControl.hidden = !isDirty;
    editorForm.dataset.filterEdited = String(isDirty);
    editorForm.dispatchEvent(new CustomEvent("ticket-filter-edited", { bubbles: true, detail: { isDirty } }));
  }

  /** 후보를 검색해도 선택한 값을 유지하는 복수 선택 입력을 생성한다. */
  function createChoiceInput(conditionNode) {
    const choices = conditionChoices(conditionNode.field);
    const picker = createElement("details", "filter-value-picker");
    const pickerSummary = createElement("summary");
    const searchControl = createElement("input");
    searchControl.type = "search";
    searchControl.placeholder = "후보 검색";
    searchControl.setAttribute("aria-label", `${fieldDefinitions[conditionNode.field].label} 후보 검색`);
    const choicesContainer = createElement("div", "filter-value-options");
    /** 선택 상태를 읽기 쉬운 문자열로 표시한다. */
    function updatePickerSummary() {
      const selectedLabels = choices.filter(choice => conditionNode.values.includes(choice[0])).map(choice => choice[1]);
      pickerSummary.textContent = selectedLabels.length ? selectedLabels.join(", ") : "값 선택";
    }
    for (const [choiceValue, choiceLabel] of choices) {
      const checkbox = createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = String(choiceValue);
      checkbox.checked = conditionNode.values.includes(choiceValue);
      const optionLabel = labelControl(choiceLabel, checkbox);
      optionLabel.dataset.searchText = choiceLabel.toLocaleLowerCase();
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          conditionNode.values.push(choiceValue);
        } else {
          conditionNode.values = conditionNode.values.filter(value => value !== choiceValue);
        }
        updatePickerSummary();
        synchronizeEditingState();
      });
      choicesContainer.append(optionLabel);
    }
    searchControl.addEventListener("input", () => {
      const searchText = searchControl.value.toLocaleLowerCase();
      for (const optionLabel of choicesContainer.children) {
        optionLabel.hidden = !optionLabel.dataset.searchText.includes(searchText);
      }
    });
    updatePickerSummary();
    picker.append(pickerSummary, searchControl, choicesContainer);
    return picker;
  }

  /** 필드와 연산자에 맞는 값 입력을 생성한다. */
  function renderConditionValues(conditionNode, valuesContainer) {
    valuesContainer.replaceChildren();
    if (["is_empty", "is_not_empty"].includes(conditionNode.operator)) return;
    const definition = fieldDefinitions[conditionNode.field];
    if (!["text", "date"].includes(definition.type)) {
      valuesContainer.append(createChoiceInput(conditionNode));
      return;
    }
    const inputCount = conditionNode.operator === "between" ? 2 : 1;
    for (let valueIndex = 0; valueIndex < inputCount; valueIndex++) {
      const valueControl = createElement("input");
      valueControl.type = definition.type === "date" ? "date" : "text";
      valueControl.required = true;
      valueControl.value = conditionNode.values[valueIndex] || "";
      if (definition.type === "text") valueControl.maxLength = 200;
      const inputLabel = inputCount === 2 ? `${definition.label} ${valueIndex === 0 ? "시작" : "종료"}` : `${definition.label} 값`;
      valueControl.addEventListener("input", () => {
        conditionNode.values[valueIndex] = valueControl.value;
        synchronizeEditingState();
      });
      valuesContainer.append(labelControl(inputLabel, valueControl));
    }
  }

  /** 조건 행의 필드 변경·제외·삭제를 연결한다. */
  function renderCondition(conditionNode, parentGroup) {
    const conditionRow = createElement("div", "filter-condition");
    const fieldSelect = createSelect(Object.entries(fieldDefinitions).map(([name, definition]) => [name, definition.label]), conditionNode.field);
    fieldSelect.dataset.conditionField = conditionNode.field;
    const operatorSelect = createSelect(conditionOperators(conditionNode.field), conditionNode.operator);
    operatorSelect.dataset.conditionOperator = "";
    const valuesContainer = createElement("div", "filter-condition-values");
    const negatedControl = createElement("input");
    negatedControl.type = "checkbox";
    negatedControl.checked = conditionNode.negated;
    negatedControl.addEventListener("change", () => {
      conditionNode.negated = negatedControl.checked;
      synchronizeEditingState();
    });
    fieldSelect.addEventListener("change", () => {
      conditionNode.field = fieldSelect.value;
      conditionNode.operator = conditionOperators(conditionNode.field)[0][0];
      conditionNode.values = [];
      renderExpression();
    });
    operatorSelect.addEventListener("change", () => {
      conditionNode.operator = operatorSelect.value;
      conditionNode.values = [];
      renderConditionValues(conditionNode, valuesContainer);
      synchronizeEditingState();
    });
    const deleteButton = createElement("button", "button quiet", "삭제");
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `${fieldDefinitions[conditionNode.field].label} 조건 삭제`);
    deleteButton.addEventListener("click", () => {
      parentGroup.children = parentGroup.children.filter(child => child !== conditionNode);
      renderExpression();
    });
    renderConditionValues(conditionNode, valuesContainer);
    conditionRow.append(labelControl("필드", fieldSelect), labelControl("연산자", operatorSelect), valuesContainer, labelControl("NOT", negatedControl), deleteButton);
    return conditionRow;
  }

  /** 그룹 범위와 AND/OR·NOT·추가 동작을 표시한다. */
  function renderGroup(groupNode, parentGroup = null, groupDepth = 1) {
    const groupContainer = createElement("div", `filter-group${parentGroup ? " nested" : ""}`);
    const groupHeader = createElement("div", "filter-group-header");
    const groupOperator = createSelect([["AND", "모두 만족 AND"], ["OR", "하나 이상 만족 OR"]], groupNode.operator);
    groupOperator.dataset.groupOperator = "";
    groupOperator.addEventListener("change", () => {
      groupNode.operator = groupOperator.value;
      synchronizeEditingState();
    });
    const groupNegation = createElement("input");
    groupNegation.type = "checkbox";
    groupNegation.checked = groupNode.negated;
    groupNegation.addEventListener("change", () => {
      groupNode.negated = groupNegation.checked;
      synchronizeEditingState();
    });
    groupHeader.append(labelControl(parentGroup ? "그룹" : "조건 조합", groupOperator), labelControl("이 그룹 제외 NOT", groupNegation));
    if (parentGroup) {
      const deleteGroupButton = createElement("button", "button quiet", "그룹 삭제");
      deleteGroupButton.type = "button";
      deleteGroupButton.addEventListener("click", () => {
        parentGroup.children = parentGroup.children.filter(child => child !== groupNode);
        renderExpression();
      });
      groupHeader.append(deleteGroupButton);
    }
    groupHeader.hidden = !parentGroup && !groupNode.children.length && !groupNode.negated;
    groupContainer.append(groupHeader);
    for (const childNode of groupNode.children) {
      groupContainer.append(childNode.kind === "group" ? renderGroup(childNode, groupNode, groupDepth + 1) : renderCondition(childNode, groupNode));
    }
    const groupActions = createElement("div", "filter-group-actions");
    const fieldAdder = createSelect([["", "필터 추가…"], ...Object.entries(fieldDefinitions).map(([name, definition]) => [name, definition.label])], "");
    fieldAdder.dataset.filterAddField = "";
    fieldAdder.setAttribute("aria-label", "필터 추가");
    fieldAdder.disabled = groupDepth >= 5;
    fieldAdder.addEventListener("change", () => {
      if (!fieldAdder.value) return;
      groupNode.children.push({ kind: "condition", field: fieldAdder.value, operator: conditionOperators(fieldAdder.value)[0][0], values: [], negated: false });
      renderExpression();
    });
    const groupAdder = createElement("button", "button quiet", "그룹 추가");
    groupAdder.type = "button";
    groupAdder.disabled = groupDepth >= 4;
    groupAdder.addEventListener("click", () => {
      groupNode.children.push({ kind: "group", operator: "AND", children: [], negated: false });
      renderExpression();
    });
    groupActions.append(fieldAdder, groupAdder);
    groupContainer.append(groupActions);
    return groupContainer;
  }

  /** 조건 트리 구조가 바뀌면 편집 UI를 다시 구성한다. */
  function renderExpression() {
    expressionContainer.replaceChildren(renderGroup(editingDefinition.expression));
    synchronizeEditingState();
  }

  /** 미완성 조건과 과도한 URL 크기를 전송 전에 검증한다. */
  function validateNode(conditionNode, depth = 1) {
    if (depth > 5) throw new Error("중첩 깊이는 5 이하여야 합니다.");
    if (conditionNode.kind === "group") {
      if (!conditionNode.children.length && (depth > 1 || conditionNode.negated)) throw new Error("빈 그룹을 제거하거나 조건을 추가하세요.");
      for (const childNode of conditionNode.children) validateNode(childNode, depth + 1);
    } else if (!["is_empty", "is_not_empty"].includes(conditionNode.operator)) {
      const expectedCount = conditionNode.operator === "between" ? 2 : null;
      if (!conditionNode.values.length || conditionNode.values.some(value => value === "") || (expectedCount && conditionNode.values.length !== expectedCount)) throw new Error("모든 조건의 값을 입력하세요.");
      if (conditionNode.values.length > 30) throw new Error("조건당 선택값은 30개 이하여야 합니다.");
      if (expectedCount && conditionNode.values[0] > conditionNode.values[1]) throw new Error("날짜 시작은 종료보다 늦을 수 없습니다.");
    }
  }

  for (const [selector, propertyName] of [["[data-filter-sort]", "sort_by"], ["[data-filter-direction]", "sort_direction"], ["[data-filter-page-size]", "page_size"]]) {
    const control = editorForm.querySelector(selector);
    if (control) control.addEventListener("change", () => {
      editingDefinition[propertyName] = propertyName === "page_size" ? Number(control.value) : control.value;
      synchronizeEditingState();
    });
  }
  editorForm.addEventListener("submit", event => {
    try {
      validateNode(editingDefinition.expression);
      const filterJson = JSON.stringify(editingDefinition);
      if (new TextEncoder().encode(filterJson).length > 4096 || encodeURIComponent(filterJson).length > 12288) throw new Error("조건 크기를 줄여 주세요. 최대 4 KiB입니다.");
      editorForm.querySelector("[data-filter-payload]").value = filterJson;
    } catch (error) {
      event.preventDefault();
      errorControl.hidden = false;
      errorControl.textContent = error.message;
    }
  });
  renderExpression();
}

for (const editorForm of document.querySelectorAll("[data-ticket-filter-editor]")) {
  initializeTicketFilterEditor(editorForm);
}
