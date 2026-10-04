/** 공개 범위별 영역에 저장·관리 동작을 연결하고 요청 대상을 고정한다. */
function initializeSavedFilterScope(panel, section) {
  const scope = section.dataset.filterScope;
  const scopeLabel = scope === "personal" ? "개인" : "공유";
  const projectKey = panel.dataset.projectKey;
  const endpoint = `/api/projects/${encodeURIComponent(projectKey)}/${scope}-filters`;
  const definition = JSON.parse(panel.querySelector("[data-applied-ticket-filter]").textContent);
  const feedback = panel.querySelector(`[data-${scope}-filter-feedback]`);
  const noticeKey = `taskflow-${scope}-filter-notice:${projectKey}`;
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
        throw new Error(error.message || `${scopeLabel} 필터를 저장하지 못했습니다. 입력을 확인하세요.`);
      }
      sessionStorage.setItem(noticeKey, successMessage);
      window.location.reload();
    } catch (error) {
      showFeedback(error.message || `${scopeLabel} 필터 처리 중 오류가 발생했습니다.`, true);
    } finally {
      requestPending = false;
    }
  }

  /** 이미 화면에 적용된 조건만 선택한 범위의 새 필터로 저장한다. */
  function createSavedFilter(event) {
    event.preventDefault();
    const name = new FormData(event.currentTarget).get("name");
    const successMessage = scope === "personal"
      ? "개인 필터를 저장했습니다. 나에게만 표시됩니다."
      : "공유 필터를 저장했습니다. 프로젝트 구성원 모두에게 표시됩니다.";
    saveChange(endpoint, "POST", { name, definition }, successMessage);
  }

  /** 선택한 필터의 이름 변경·덮어쓰기·삭제 요청을 구성한다. */
  function manageSavedFilter(event) {
    const button = event.target.closest("[data-filter-action]");
    if (!button || requestPending) return;
    const row = button.closest(`[data-${scope}-filter-id]`);
    const name = row.querySelector(`[data-${scope}-filter-name]`).textContent;
    const payload = { expected_updated_at: row.dataset.updatedAt };
    const url = `${endpoint}/${row.getAttribute(`data-${scope}-filter-id`)}`;
    if (button.dataset.filterAction === "rename") {
      const renamed = window.prompt(`${scopeLabel} 필터의 새 이름을 입력하세요.`, name);
      if (renamed === null) return;
      payload.name = renamed;
      saveChange(url, "PATCH", payload, `${scopeLabel} 필터 이름을 변경했습니다.`);
    } else if (button.dataset.filterAction === "overwrite") {
      if (!window.confirm(`'${name}' ${scopeLabel} 필터를 현재 적용된 조건으로 덮어쓰시겠습니까?`)) return;
      payload.definition = definition;
      saveChange(url, "PATCH", payload, `${scopeLabel} 필터 조건을 변경했습니다.`);
    } else if (button.dataset.filterAction === "delete") {
      if (!window.confirm(`'${name}' ${scopeLabel} 필터를 삭제하시겠습니까?`)) return;
      saveChange(url, "DELETE", payload, `${scopeLabel} 필터를 삭제했습니다.`);
    }
  }

  const createForm = section.querySelector(`[data-${scope}-filter-create]`);
  if (createForm) createForm.addEventListener("submit", createSavedFilter);
  section.addEventListener("click", manageSavedFilter);
}

const savedFilterPanel = document.querySelector("[data-personal-filters]");
if (savedFilterPanel) {
  for (const section of savedFilterPanel.querySelectorAll("[data-filter-scope]")) {
    initializeSavedFilterScope(savedFilterPanel, section);
  }
}
