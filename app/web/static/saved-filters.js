/** 개인·공유 필터의 불러오기와 관리를 공통 선택창에 연결한다. */
function initializeSavedFilters(panel) {
  const projectKey = panel.dataset.projectKey;
  const selection = panel.querySelector("[data-saved-filter-selection]");
  const feedback = panel.querySelector("[data-saved-filter-feedback]");
  const description = panel.querySelector("[data-saved-filter-description]");
  const dialog = panel.querySelector("[data-saved-filter-dialog]");
  const createForm = panel.querySelector("[data-saved-filter-create]");
  const editor = document.querySelector("[data-ticket-filter-editor]");
  const appliedDefinition = JSON.parse(panel.querySelector("[data-applied-ticket-filter]").textContent);
  const noticeKey = `taskflow-filter-notice:${projectKey}`;
  let requestPending = false;

  /** 서버 응답과 이름을 HTML로 해석하지 않고 표시한다. */
  function showFeedback(message, isError = false) {
    feedback.hidden = false;
    feedback.textContent = message;
    feedback.classList.toggle("error", isError);
    feedback.classList.toggle("success", !isError);
  }

  /** 선택한 공개 범위의 서버 endpoint와 최신 수정 시각을 반환한다. */
  function selectedFilter() {
    if (!selection.value) return null;
    const [scope, identifier] = selection.value.split(":");
    const selectedOption = selection.selectedOptions[0];
    return {
      scope, identifier, name: selectedOption.textContent,
      updatedAt: selectedOption.dataset.updatedAt,
      endpoint: `/api/projects/${encodeURIComponent(projectKey)}/${scope}-filters/${identifier}`,
      canManage: scope === "personal" || panel.dataset.canManageShared === "true",
    };
  }

  /** 공개 범위·관리 권한·미적용 편집에 맞게 동작을 표시한다. */
  function synchronizeControls() {
    const savedFilter = selectedFilter();
    const isDirty = editor.dataset.filterEdited === "true";
    for (const action of ["rename", "overwrite", "delete"]) {
      const button = panel.querySelector(`[data-saved-filter-action="${action}"]`);
      button.hidden = !savedFilter?.canManage;
      button.disabled = requestPending || (action === "overwrite" && isDirty);
    }
    panel.querySelector('[data-saved-filter-action="load"]').disabled = !savedFilter || requestPending;
    panel.querySelector('[data-saved-filter-action="create"]').disabled = requestPending || isDirty;
    const currentParameters = new URL(window.location.href).searchParams;
    const isApplied = savedFilter && currentParameters.get("loaded_scope") === savedFilter.scope && currentParameters.get("loaded_id") === savedFilter.identifier;
    const selectedLabel = savedFilter ? `${isApplied ? "불러온" : "선택한"} 필터: ${savedFilter.name} · ${savedFilter.scope === "personal" ? "나만 보기" : "구성원 공용"}. ` : "";
    description.textContent = selectedLabel + (isDirty ? "편집한 조건을 먼저 적용한 뒤 저장하세요." : "마지막으로 적용한 조건·정렬·표시 개수를 저장합니다. 공유 필터는 프로젝트 관리자가 관리합니다.");
  }

  /** CSRF와 optimistic locking을 적용하고 성공한 필터의 선택 상태를 유지한다. */
  async function saveChange(endpoint, method, payload, scope, successMessage) {
    if (requestPending) return;
    requestPending = true;
    synchronizeControls();
    try {
      const response = await fetch(endpoint, {
        method, credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": panel.dataset.csrfToken },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errorResponse = await response.json();
        throw new Error(errorResponse.message || "필터를 저장하지 못했습니다.");
      }
      const nextLocation = new URL(window.location.href);
      if (method === "DELETE") {
        nextLocation.searchParams.delete("loaded_scope");
        nextLocation.searchParams.delete("loaded_id");
      } else {
        const savedFilter = await response.json();
        nextLocation.searchParams.set("loaded_scope", scope);
        nextLocation.searchParams.set("loaded_id", savedFilter.id);
      }
      sessionStorage.setItem(noticeKey, successMessage);
      window.location.assign(nextLocation.href);
    } catch (error) {
      showFeedback(error.message || "필터 처리 중 오류가 발생했습니다.", true);
      requestPending = false;
      synchronizeControls();
    }
  }

  /** 선택한 필터를 적용하거나 마지막 적용 조건을 관리한다. */
  function handleSavedFilterAction(event) {
    const button = event.target.closest("[data-saved-filter-action]");
    if (!button || requestPending) return;
    const action = button.dataset.savedFilterAction;
    if (action === "create") {
      if (editor.dataset.filterEdited === "true") return;
      createForm.reset();
      dialog.showModal();
      createForm.elements.name.focus();
      return;
    }
    const savedFilter = selectedFilter();
    if (!savedFilter) return;
    if (action === "load") {
      window.location.assign(`/projects/${encodeURIComponent(projectKey)}/${savedFilter.scope}-filters/${savedFilter.identifier}/apply?view=${panel.dataset.view}`);
      return;
    }
    if (!savedFilter.canManage) return;
    const payload = { expected_updated_at: savedFilter.updatedAt };
    if (action === "rename") {
      const name = window.prompt("새 필터 이름을 입력하세요.", savedFilter.name);
      if (name === null) return;
      payload.name = name;
      saveChange(savedFilter.endpoint, "PATCH", payload, savedFilter.scope, "필터 이름을 변경했습니다.");
    } else if (action === "overwrite") {
      if (editor.dataset.filterEdited === "true") return;
      if (!window.confirm(`'${savedFilter.name}' 필터를 현재 적용된 조건으로 덮어쓰시겠습니까?`)) return;
      payload.definition = appliedDefinition;
      saveChange(savedFilter.endpoint, "PATCH", payload, savedFilter.scope, "필터 조건을 변경했습니다.");
    } else if (action === "delete") {
      if (!window.confirm(`'${savedFilter.name}' 필터를 삭제하시겠습니까?`)) return;
      saveChange(savedFilter.endpoint, "DELETE", payload, savedFilter.scope, "필터를 삭제했습니다.");
    }
  }

  createForm.addEventListener("submit", event => {
    event.preventDefault();
    if (editor.dataset.filterEdited === "true") return;
    const scope = createForm.elements.scope.value;
    const endpoint = `/api/projects/${encodeURIComponent(projectKey)}/${scope}-filters`;
    saveChange(endpoint, "POST", { name: createForm.elements.name.value, definition: appliedDefinition }, scope, scope === "personal" ? "개인 필터를 저장했습니다. 나에게만 표시됩니다." : "공유 필터를 저장했습니다. 프로젝트 구성원 모두에게 표시됩니다.");
  });
  panel.querySelector("[data-saved-filter-cancel]").addEventListener("click", () => dialog.close());
  selection.addEventListener("change", synchronizeControls);
  editor.addEventListener("ticket-filter-edited", synchronizeControls);
  panel.addEventListener("click", handleSavedFilterAction);
  const savedNotice = sessionStorage.getItem(noticeKey);
  if (savedNotice) {
    sessionStorage.removeItem(noticeKey);
    showFeedback(savedNotice);
  }
  synchronizeControls();
}

for (const savedFilterPanel of document.querySelectorAll("[data-saved-filters]")) {
  initializeSavedFilters(savedFilterPanel);
}
