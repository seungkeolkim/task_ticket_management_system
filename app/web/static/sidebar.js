(() => {
  "use strict";

  const SIDEBAR_STATE_KEY = "taskflow.sidebar.collapsed";
  const sidebarLayout = document.querySelector("[data-sidebar-layout]");
  const sidebar = document.querySelector("[data-sidebar]");
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
  const sidebarToggleIcon = document.querySelector("[data-sidebar-toggle-icon]");

  if (!sidebarLayout || !sidebar || !sidebarToggle || !sidebarToggleIcon) return;

  /** 저장된 sidebar 상태를 읽되 browser 저장소 접근 실패 시 기본값을 사용한다. */
  const readCollapsedState = () => {
    try {
      return window.localStorage.getItem(SIDEBAR_STATE_KEY) === "true";
    } catch (_error) {
      return false;
    }
  };

  /** sidebar 상태를 저장하되 제한된 browser 환경에서도 화면 동작은 유지한다. */
  const saveCollapsedState = (isCollapsed) => {
    try {
      window.localStorage.setItem(SIDEBAR_STATE_KEY, String(isCollapsed));
    } catch (_error) {
      // 저장소를 사용할 수 없어도 현재 page의 toggle 동작은 유지한다.
    }
  };

  /** sidebar 표시, 접근성 속성, toggle 안내를 한 상태로 동기화한다. */
  const applyCollapsedState = (isCollapsed) => {
    sidebarLayout.classList.toggle("is-sidebar-collapsed", isCollapsed);
    sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
    sidebarToggle.setAttribute(
      "aria-label",
      isCollapsed ? "네비게이션 펼치기" : "네비게이션 접기",
    );
    sidebarToggle.setAttribute(
      "title",
      isCollapsed ? "네비게이션 펼치기" : "네비게이션 접기",
    );
    sidebarToggleIcon.textContent = isCollapsed ? "›" : "‹";
    sidebar.setAttribute("aria-hidden", String(isCollapsed));
    sidebar.toggleAttribute("inert", isCollapsed);
  };

  applyCollapsedState(readCollapsedState());
  sidebarToggle.addEventListener("click", () => {
    const isCollapsed = !sidebarLayout.classList.contains("is-sidebar-collapsed");
    applyCollapsedState(isCollapsed);
    saveCollapsedState(isCollapsed);
  });
})();
