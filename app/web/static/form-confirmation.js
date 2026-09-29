(() => {
  "use strict";

  /** 확인 문구가 지정된 form을 제출하기 전에 사용자의 최종 의사를 확인한다. */
  const confirmFormSubmission = (event) => {
    if (event.defaultPrevented) return;

    const formElement = event.target.closest("form[data-confirm-message]");
    if (!formElement) return;

    if (!window.confirm(formElement.dataset.confirmMessage)) {
      event.preventDefault();
    }
  };

  document.addEventListener("submit", confirmFormSubmission);
})();
