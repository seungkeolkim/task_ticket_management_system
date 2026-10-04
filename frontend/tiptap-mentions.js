import { Node } from '@tiptap/core'

export const UserMention = Node.create({
  name: 'mention',
  group: 'inline',
  inline: true,
  atom: true,
  /** 안정적인 사용자 ID와 저장 시점 표시 이름을 선언한다. */
  addAttributes() {
    return { userId: { default: null }, label: { default: '' } }
  },
  /** 복사된 내부 멘션 요소를 구조화 node로 읽는다. */
  parseHTML() {
    return [{
      tag: 'span[data-mention-user-id]',
      getAttrs: element => ({
        userId: Number(element.getAttribute('data-mention-user-id')),
        label: element.textContent.replace(/^@/, ''),
      }),
    }]
  },
  /** 표시 문자열을 HTML 해석 없이 text child로 렌더링한다. */
  renderHTML({ node }) {
    return ['span', { 'data-mention-user-id': node.attrs.userId }, `@${node.attrs.label}`]
  },
  /** 클립보드의 plain text 표현을 제공한다. */
  renderText({ node }) {
    return `@${node.attrs.label}`
  },
})

/** editor별 비동기 후보 검색과 키보드·마우스 선택을 연결한다. */
export function initializeMentions(editor, fieldElement, formElement) {
  const projectMatch = new URL(formElement.action, window.location.href).pathname.match(/^\/projects\/([^/]+)\//)
  if (!projectMatch) return
  const candidateUrl = `/api/projects/${projectMatch[1]}/mention-candidates`
  const resultsElement = document.createElement('div')
  resultsElement.className = 'mention-suggestions'
  resultsElement.setAttribute('aria-label', '멘션 사용자 후보')
  resultsElement.hidden = true
  fieldElement.append(resultsElement)
  let currentRange = null
  let candidateUsers = []
  let selectedIndex = 0
  let requestGeneration = 0
  let searchTimer = null

  /** 오래된 검색 결과와 선택 범위를 함께 폐기한다. */
  function hideCandidates() {
    requestGeneration += 1
    clearTimeout(searchTimer)
    currentRange = null
    candidateUsers = []
    resultsElement.hidden = true
  }

  /** 현재 후보를 atom으로 삽입하고 다음 입력용 공백을 만든다. */
  function insertCandidate(candidate) {
    if (!currentRange) return
    const insertionRange = currentRange
    hideCandidates()
    editor.chain().focus().insertContentAt(insertionRange, [
      { type: 'mention', attrs: { userId: candidate.id, label: candidate.display_name } },
      { type: 'text', text: ' ' },
    ]).run()
  }

  /** 후보의 표시 이름과 로그인 ID를 안전한 button text로 표시한다. */
  function renderCandidates() {
    resultsElement.replaceChildren()
    if (!candidateUsers.length) {
      resultsElement.textContent = '일치하는 활성 구성원이 없습니다.'
      return
    }
    for (let candidateIndex = 0; candidateIndex < candidateUsers.length; candidateIndex += 1) {
      const candidate = candidateUsers[candidateIndex]
      const button = document.createElement('button')
      button.type = 'button'
      button.textContent = `${candidate.display_name} (${candidate.login_id})`
      button.classList.toggle('is-selected', candidateIndex === selectedIndex)
      button.addEventListener('mousedown', event => event.preventDefault())
      button.addEventListener('click', () => insertCandidate(candidate))
      resultsElement.append(button)
    }
  }

  /** caret 직전 @검색어를 읽고 최신 요청에 한해 결과를 적용한다. */
  function refreshCandidates() {
    const { empty, from, $from } = editor.state.selection
    hideCandidates()
    if (!empty || editor.isActive('codeBlock') || editor.isActive('code')) return
    const precedingText = $from.parent.textBetween(0, $from.parentOffset, '\n', '\ufffc')
    const matchedQuery = precedingText.match(/(?:^|\s)@([^@\n]{0,100})$/)
    if (!matchedQuery) return
    const query = matchedQuery[1]
    currentRange = { from: from - query.length - 1, to: from }
    const generation = requestGeneration
    resultsElement.hidden = false
    resultsElement.textContent = '구성원을 검색하고 있습니다.'
    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`${candidateUrl}?query=${encodeURIComponent(query)}`)
        if (!response.ok) throw new Error('candidate request failed')
        const candidates = await response.json()
        if (generation !== requestGeneration) return
        candidateUsers = candidates
        selectedIndex = 0
        renderCandidates()
      } catch (_error) {
        if (generation === requestGeneration) {
          resultsElement.textContent = '구성원을 불러오지 못했습니다. 다시 입력해 주세요.'
        }
      }
    }, 150)
  }

  editor.on('update', refreshCandidates)
  editor.on('selectionUpdate', refreshCandidates)
  editor.on('destroy', hideCandidates)
  editor.view.dom.addEventListener('keydown', event => {
    if (resultsElement.hidden || event.isComposing) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      hideCandidates()
    } else if (candidateUsers.length && ['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) {
      event.preventDefault()
      event.stopImmediatePropagation()
      if (event.key === 'Enter') {
        insertCandidate(candidateUsers[selectedIndex])
      } else {
        const direction = event.key === 'ArrowDown' ? 1 : -1
        selectedIndex = (selectedIndex + direction + candidateUsers.length) % candidateUsers.length
        renderCandidates()
      }
    }
  }, true)
  fieldElement.addEventListener('focusout', event => {
    if (!fieldElement.contains(event.relatedTarget)) hideCandidates()
  })
  const mentionButton = document.createElement('button')
  mentionButton.type = 'button'
  mentionButton.textContent = '@'
  mentionButton.setAttribute('aria-label', '사용자 멘션')
  mentionButton.title = '사용자 멘션 (@ 입력 후 선택)'
  mentionButton.addEventListener('click', () => editor.chain().focus().insertContent(' @').run())
  fieldElement.querySelector('[data-rich-text-toolbar]').append(mentionButton)
}
