/** 서버가 렌더링한 본인 필터 영역에 저장·관리 동작을 연결한다. */
function initializePersonalFilters() {
  const panel = document.querySelector("[data-personal-filters]");
  if (!panel) return;
  const projectKey = panel.dataset.projectKey;
  const endpoint = `/api/projects/${encodeURIComponent(projectKey)}/personal-filters`;
  const definition = JSON.parse(panel.querySelector("[data-applied-ticket-filter]").textContent);
  const feedback = panel.querySelector("[data-personal-filter-feedback]");
  const noticeKey = `taskflow-personal-filter-notice:${projectKey}`;
  let requestPending = false;

  /** 필터 이름이나 서버 응답을 HTML로 해석하지 않고 결과를 표시한다. */
  function showFeedback(message, isError = false) {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.classList.toggle("error", isError);
    feedback.classList.toggle("success", !isError);
  }

  const savedNotice = sessionStorage.getItem(noticeKey);
  if (savedNotice) {
    sessionStorage.removeItem(noticeKey);
    showFeedback(savedNotice);
  }

  /** CSRF와 최신 수정 시각을 전달하고 성공 후 현재 조건의 화면을 다시 조회한다. */
  async function saveChange(url, method, payload, successMessage) {
    if (requestPending) return;
    requestPending = true;
    try {
      const response = await fetch(url, {
        method, credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": panel.dataset.csrfToken },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.message || "개인 필터를 저장하지 못했습니다. 입력을 확인하세요.");
      }
      sessionStorage.setItem(noticeKey, successMessage);
      window.location.reload();
    } catch (error) {
      showFeedback(error.message || "개인 필터 처리 중 오류가 발생했습니다.", true);
    } finally {
      requestPending = false;
    }
  }

  /** 이미 화면에 적용된 조건만 본인 소유의 새 필터로 저장한다. */
  function createPersonalFilter(event) {
    event.preventDefault();
    const name = new FormData(event.currentTarget).get("name");
    saveChange(endpoint, "POST", { name, definition }, "개인 필터를 저장했습니다. 나에게만 표시됩니다.");
  }

  /** 선택한 개인 필터의 이름 변경·덮어쓰기·삭제 요청을 구성한다. */
  function managePersonalFilter(event) {
    const button = event.target.closest("[data-filter-action]");
    if (!button || requestPending) return;
    const row = button.closest("[data-personal-filter-id]");
    const name = row.querySelector("[data-personal-filter-name]").textContent;
    const payload = { expected_updated_at: row.dataset.updatedAt };
    const url = `${endpoint}/${row.dataset.personalFilterId}`;
    if (button.dataset.filterAction === "rename") {
      const renamed = window.prompt("개인 필터의 새 이름을 입력하세요.", name);
      if (renamed === null) return;
      payload.name = renamed;
      saveChange(url, "PATCH", payload, "개인 필터 이름을 변경했습니다.");
    } else if (button.dataset.filterAction === "overwrite") {
      if (!window.confirm(`'${name}' 개인 필터를 현재 적용된 조건으로 덮어쓰시겠습니까?`)) return;
      payload.definition = definition;
      saveChange(url, "PATCH", payload, "개인 필터 조건을 변경했습니다.");
    } else if (button.dataset.filterAction === "delete") {
      if (!window.confirm(`'${name}' 개인 필터를 삭제하시겠습니까?`)) return;
      saveChange(url, "DELETE", payload, "개인 필터를 삭제했습니다.");
    }
  }

  panel.querySelector("[data-personal-filter-create]").addEventListener("submit", createPersonalFilter);
  panel.addEventListener("click", managePersonalFilter);
}

initializePersonalFilters();
