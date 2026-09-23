(() => {
  "use strict";

  const root = document.querySelector("#kanban-root");
  const feedback = document.querySelector("#board-feedback");
  if (!root || !feedback) return;

  const projectKey = root.dataset.projectKey;
  const csrfToken = root.dataset.csrfToken;
  const noticeKey = `taskflow-board-notice:${projectKey}`;
  let draggedCard = null;

  const showFeedback = (message, isError = false) => {
    feedback.textContent = message;
    feedback.classList.toggle("error", isError);
    feedback.classList.toggle("success", !isError);
    feedback.hidden = false;
  };

  const savedNotice = window.sessionStorage.getItem(noticeKey);
  if (savedNotice) {
    window.sessionStorage.removeItem(noticeKey);
    showFeedback(savedNotice);
  }

  const allowedStatuses = (card) =>
    new Set((card.dataset.allowedStatuses || "").split(",").filter(Boolean));

  const canMoveTo = (card, status) => {
    if (!allowedStatuses(card).has(status)) return false;
    return !(status === "DONE" && card.dataset.completionBlocked === "true");
  };

  const clearDropState = () => {
    root
      .querySelectorAll(".is-drop-allowed,.is-drop-blocked,.is-drag-over")
      .forEach((column) =>
        column.classList.remove("is-drop-allowed", "is-drop-blocked", "is-drag-over")
      );
  };

  const markDropTargets = (card) => {
    const board = card.closest(".kanban-board");
    if (!board) return;
    board.querySelectorAll("[data-board-column]").forEach((column) => {
      const status = column.dataset.status;
      if (status === card.dataset.currentStatus) return;
      column.classList.add(canMoveTo(card, status) ? "is-drop-allowed" : "is-drop-blocked");
    });
  };

  const transition = async (card, targetStatus, select) => {
    const currentStatus = card.dataset.currentStatus;
    if (!canMoveTo(card, targetStatus)) {
      if (select) select.value = currentStatus;
      showFeedback("현재 상태에서는 선택한 상태로 이동할 수 없습니다.", true);
      return;
    }

    card.classList.add("is-updating");
    if (select) select.disabled = true;
    showFeedback(`${card.dataset.ticketKey} 상태를 변경하는 중입니다.`);
    try {
      const response = await window.fetch(
        `/api/projects/${encodeURIComponent(projectKey)}/tickets/${encodeURIComponent(card.dataset.ticketKey)}/transitions`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({
            target_status: targetStatus,
            expected_version: Number(card.dataset.version),
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        const message = payload.message || "상태를 변경하지 못했습니다.";
        if (response.status === 409) {
          window.sessionStorage.setItem(
            noticeKey,
            `${message} 최신 보드를 다시 불러왔습니다.`
          );
          window.location.reload();
          return;
        }
        throw new Error(message);
      }
      window.sessionStorage.setItem(
        noticeKey,
        `${card.dataset.ticketKey} 상태를 변경했습니다.`
      );
      window.location.reload();
    } catch (error) {
      card.classList.remove("is-updating");
      if (select) {
        select.disabled = false;
        select.value = currentStatus;
      }
      showFeedback(error.message || "상태 변경 중 오류가 발생했습니다.", true);
    }
  };

  root.querySelectorAll(".kanban-card[draggable='true']").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      draggedCard = card;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.ticketKey);
      markDropTargets(card);
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      draggedCard = null;
      clearDropState();
    });
  });

  root.querySelectorAll("[data-board-column]").forEach((column) => {
    column.addEventListener("dragover", (event) => {
      if (
        !draggedCard ||
        column.closest(".kanban-board") !== draggedCard.closest(".kanban-board") ||
        !canMoveTo(draggedCard, column.dataset.status)
      ) {
        return;
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      column.classList.add("is-drag-over");
    });
    column.addEventListener("dragleave", () => column.classList.remove("is-drag-over"));
    column.addEventListener("drop", (event) => {
      event.preventDefault();
      column.classList.remove("is-drag-over");
      if (
        draggedCard &&
        column.closest(".kanban-board") === draggedCard.closest(".kanban-board")
      ) {
        transition(draggedCard, column.dataset.status, null);
      }
    });
  });

  root.querySelectorAll("[data-board-status]").forEach((select) => {
    select.addEventListener("change", () => {
      const card = select.closest(".kanban-card");
      if (card) transition(card, select.value, select);
    });
  });
})();
