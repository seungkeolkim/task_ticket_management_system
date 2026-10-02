(() => {
  "use strict";

  const ticketTypeSelect = document.querySelector("[data-ticket-type-select]");
  const parentTicketSelect = document.querySelector("[data-ticket-parent-select]");
  if (!ticketTypeSelect || !parentTicketSelect) return;

  const emptyOption = parentTicketSelect.querySelector("[data-parent-empty-option]");
  const parentOptions = parentTicketSelect.querySelectorAll("[data-parent-type]");

  /** 선택한 티켓 유형에 맞게 상위 티켓 후보와 필수 여부를 갱신한다. */
  const updateParentTicketOptions = () => {
    const selectedTicketType = ticketTypeSelect.value;
    const allowedParentType =
      selectedTicketType === "TASK"
        ? "EPIC"
        : selectedTicketType === "SUBTASK"
          ? "TASK"
          : null;

    parentTicketSelect.disabled = allowedParentType === null;
    parentTicketSelect.required = selectedTicketType === "SUBTASK";

    if (emptyOption) {
      emptyOption.textContent =
        selectedTicketType === "EPIC"
          ? "상위 티켓 없음"
          : selectedTicketType === "SUBTASK"
            ? "Task를 선택하세요"
            : "선택하지 않음";
    }

    for (const parentOption of parentOptions) {
      const isAllowed = parentOption.dataset.parentType === allowedParentType;
      parentOption.hidden = !isAllowed;
      parentOption.disabled = !isAllowed;
    }

    const selectedParentOption = parentTicketSelect.selectedOptions[0];
    if (parentTicketSelect.disabled || selectedParentOption?.disabled) {
      parentTicketSelect.value = "";
    }
  };

  ticketTypeSelect.addEventListener("change", updateParentTicketOptions);
  updateParentTicketOptions();
})();
