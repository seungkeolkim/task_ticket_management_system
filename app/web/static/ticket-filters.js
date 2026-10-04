/** 담당자 미지정 조건과 담당자 선택 control의 활성 상태를 동기화한다. */
function synchronizeTicketAssigneeFilter(event) {
  const unassignedControl = event.currentTarget;
  const assigneeControl = unassignedControl.form.querySelector('[name="assignee_id"]');
  if (assigneeControl) {
    assigneeControl.disabled = unassignedControl.checked;
  }
}

for (const unassignedControl of document.querySelectorAll('.ticket-filter-toolbar [name="unassigned"]')) {
  unassignedControl.addEventListener("change", synchronizeTicketAssigneeFilter);
}
