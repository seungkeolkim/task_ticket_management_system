import { Editor, Node } from '@tiptap/core'
import Color from '@tiptap/extension-color'
import { TableKit } from '@tiptap/extension-table'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import { FontSize, TextStyle } from '@tiptap/extension-text-style'
import StarterKit from '@tiptap/starter-kit'

const EMPTY_DOCUMENT = { type: 'doc', content: [{ type: 'paragraph' }] }
const activeImageUploadUrls = new Set()

const AttachmentImage = Node.create({
  name: 'image',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes() {
    return {
      attachmentId: { default: null },
      alt: { default: null },
      title: { default: null },
    }
  },
  parseHTML() {
    return [
      {
        tag: 'img[data-attachment-id]',
        getAttrs: (element) => ({
          attachmentId: Number(element.getAttribute('data-attachment-id')),
          alt: element.getAttribute('alt'),
          title: element.getAttribute('title'),
        }),
      },
    ]
  },
  renderHTML({ node }) {
    const attributes = {
      src: `/attachments/${node.attrs.attachmentId}`,
      'data-attachment-id': String(node.attrs.attachmentId),
      alt: node.attrs.alt || '',
    }
    if (node.attrs.title) attributes.title = node.attrs.title
    return ['img', attributes]
  },
})

/** hidden payload에서 초기 Tiptap document를 읽는다. */
function readInitialDocument(payloadElement) {
  try {
    return JSON.parse(payloadElement.value)
  } catch (_error) {
    return EMPTY_DOCUMENT
  }
}

/** 현재 editor JSON을 form payload에 반영한다. */
function synchronizePayload(editor, payloadElement) {
  payloadElement.value = JSON.stringify(editor.getJSON())
}

/** toolbar button의 활성·비활성 상태를 현재 selection에 맞춘다. */
function updateToolbarState(editor, toolbarElement) {
  const markCommands = ['bold', 'italic', 'underline', 'strike', 'code', 'link']
  for (const commandName of markCommands) {
    const button = toolbarElement.querySelector(`[data-rich-text-command="${commandName}"]`)
    button?.classList.toggle('is-active', editor.isActive(commandName))
  }
  const nodeCommands = ['bulletList', 'orderedList', 'taskList', 'blockquote', 'codeBlock']
  for (const commandName of nodeCommands) {
    const button = toolbarElement.querySelector(`[data-rich-text-command="${commandName}"]`)
    button?.classList.toggle('is-active', editor.isActive(commandName))
  }

  const headingSelect = toolbarElement.querySelector('[data-rich-text-command="heading"]')
  const activeHeadingLevel = [1, 2, 3].find((level) => editor.isActive('heading', { level }))
  if (headingSelect) headingSelect.value = activeHeadingLevel ? String(activeHeadingLevel) : 'paragraph'

  const textStyleAttributes = editor.getAttributes('textStyle')
  const fontSizeSelect = toolbarElement.querySelector('[data-rich-text-command="fontSize"]')
  const colorSelect = toolbarElement.querySelector('[data-rich-text-command="color"]')
  if (fontSizeSelect) fontSizeSelect.value = textStyleAttributes.fontSize || ''
  if (colorSelect) colorSelect.value = textStyleAttributes.color || ''

  const fieldElement = toolbarElement.closest('.rich-text-field')
  const tableToolbarElement = fieldElement?.querySelector('[data-rich-text-table-toolbar]')
  const tableIsActive = editor.isActive('table')
  if (tableToolbarElement) tableToolbarElement.hidden = !tableIsActive
  toolbarElement
    .querySelector('[data-rich-text-command="insertTable"]')
    ?.classList.toggle('is-active', tableIsActive)

  const listIsActive = ['listItem', 'taskItem'].some((nodeType) => editor.isActive(nodeType))
  for (const commandName of ['indent', 'outdent']) {
    const button = toolbarElement.querySelector(`[data-rich-text-command="${commandName}"]`)
    if (button) button.disabled = !listIsActive
  }
}

/** select 기반 toolbar command를 실행한다. */
function executeSelectCommand(editor, commandName, selectedValue) {
  if (commandName === 'heading') {
    if (selectedValue === 'paragraph') {
      editor.chain().focus().setParagraph().run()
      return
    }
    editor.chain().focus().toggleHeading({ level: Number(selectedValue) }).run()
    return
  }
  if (commandName === 'fontSize') {
    const command = editor.chain().focus()
    if (selectedValue) {
      command.setFontSize(selectedValue).run()
    } else {
      command.unsetFontSize().run()
    }
    return
  }
  if (commandName === 'color') {
    const command = editor.chain().focus()
    if (selectedValue) {
      command.setColor(selectedValue).run()
    } else {
      command.unsetColor().run()
    }
  }
}

/** 입력한 link URL이 서버 저장 계약에서 허용되는 명시적 주소인지 확인한다. */
function isAllowedLinkUrl(linkUrl) {
  if (!linkUrl || /[\s\\\u0000-\u001f\u007f]/.test(linkUrl) || linkUrl.startsWith('//')) {
    return false
  }
  if (linkUrl.startsWith('/') || linkUrl.startsWith('#')) {
    return true
  }
  try {
    const parsedUrl = new URL(linkUrl)
    return (
      ['http:', 'https:'].includes(parsedUrl.protocol) &&
      Boolean(parsedUrl.host) &&
      !parsedUrl.username &&
      !parsedUrl.password
    )
  } catch (_error) {
    return false
  }
}

/** editor별 link dialog를 연결하고 현재 selection의 link 편집 함수를 반환한다. */
function initializeLinkDialog(editor, fieldElement) {
  const dialogElement = fieldElement.querySelector('[data-rich-text-link-dialog]')
  const inputElement = dialogElement?.querySelector('[data-rich-text-link-input]')
  const errorElement = dialogElement?.querySelector('[data-rich-text-link-error]')
  const cancelButton = dialogElement?.querySelector('[data-rich-text-link-cancel]')
  const removeButton = dialogElement?.querySelector('[data-rich-text-link-remove]')
  const saveButton = dialogElement?.querySelector('[data-rich-text-link-save]')
  if (
    !dialogElement ||
    !inputElement ||
    !errorElement ||
    !cancelButton ||
    !removeButton ||
    !saveButton
  ) {
    return null
  }

  const hideError = () => {
    errorElement.textContent = ''
    errorElement.hidden = true
  }
  const closeDialog = () => {
    hideError()
    dialogElement.close()
  }
  cancelButton.addEventListener('click', closeDialog)
  removeButton.addEventListener('click', () => {
    editor.chain().focus().extendMarkRange('link').unsetLink().run()
    closeDialog()
  })
  saveButton.addEventListener('click', () => {
    const linkUrl = inputElement.value.trim()
    if (!isAllowedLinkUrl(linkUrl)) {
      errorElement.textContent =
        '외부 링크는 http:// 또는 https://로 시작해야 합니다. 입력한 주소는 자동으로 변경하지 않습니다.'
      errorElement.hidden = false
      inputElement.focus()
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: linkUrl }).run()
    closeDialog()
  })
  inputElement.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    saveButton.click()
  })

  return () => {
    const currentUrl = editor.getAttributes('link').href || ''
    inputElement.value = currentUrl
    removeButton.disabled = !currentUrl
    hideError()
    dialogElement.showModal()
    inputElement.focus()
    inputElement.select()
  }
}

/** button 기반 toolbar command를 실행한다. */
function executeButtonCommand(editor, commandName) {
  const adjustListIndent = (direction) => {
    for (const listItemType of ['listItem', 'taskItem']) {
      if (!editor.isActive(listItemType)) continue
      const command = editor.chain().focus()
      return direction === 'indent'
        ? command.sinkListItem(listItemType).run()
        : command.liftListItem(listItemType).run()
    }
    return false
  }
  const commands = {
    bold: () => editor.chain().focus().toggleBold().run(),
    italic: () => editor.chain().focus().toggleItalic().run(),
    underline: () => editor.chain().focus().toggleUnderline().run(),
    strike: () => editor.chain().focus().toggleStrike().run(),
    bulletList: () => editor.chain().focus().toggleBulletList().run(),
    orderedList: () => editor.chain().focus().toggleOrderedList().run(),
    taskList: () => editor.chain().focus().toggleTaskList().run(),
    indent: () => adjustListIndent('indent'),
    outdent: () => adjustListIndent('outdent'),
    blockquote: () => editor.chain().focus().toggleBlockquote().run(),
    code: () => editor.chain().focus().toggleCode().run(),
    codeBlock: () => editor.chain().focus().toggleCodeBlock().run(),
    insertTable: () =>
      editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
    addRowBefore: () => editor.chain().focus().addRowBefore().run(),
    addRowAfter: () => editor.chain().focus().addRowAfter().run(),
    deleteRow: () => editor.chain().focus().deleteRow().run(),
    addColumnBefore: () => editor.chain().focus().addColumnBefore().run(),
    addColumnAfter: () => editor.chain().focus().addColumnAfter().run(),
    deleteColumn: () => editor.chain().focus().deleteColumn().run(),
    deleteTable: () => editor.chain().focus().deleteTable().run(),
    undo: () => editor.chain().focus().undo().run(),
    redo: () => editor.chain().focus().redo().run(),
  }
  commands[commandName]?.()
}

/** 같은 티켓을 사용하는 editor와 form의 최신 optimistic-lock version을 동기화한다. */
function updateTicketVersion(uploadUrl, ticketVersion) {
  for (const editorElement of document.querySelectorAll('[data-rich-text-image-upload-url]')) {
    if (editorElement.dataset.richTextImageUploadUrl === uploadUrl) {
      editorElement.dataset.richTextImageTicketVersion = String(ticketVersion)
    }
  }
  for (const versionInput of document.querySelectorAll('[data-ticket-expected-version]')) {
    versionInput.value = String(ticketVersion)
  }
}

/** 동일 티켓의 image upload button을 함께 잠그거나 해제한다. */
function setImageUploadButtonsDisabled(uploadUrl, disabled) {
  for (const editorElement of document.querySelectorAll('[data-rich-text-image-upload-url]')) {
    if (editorElement.dataset.richTextImageUploadUrl !== uploadUrl) continue
    const fieldElement = editorElement.closest('.rich-text-field')
    const uploadButton = fieldElement?.querySelector('[data-rich-text-command="uploadImage"]')
    if (uploadButton) uploadButton.disabled = disabled
  }
}

/** 선택한 image를 일반 첨부파일로 올린 뒤 현재 selection에 image node를 삽입한다. */
async function uploadEditorImage(editor, editorElement, formElement, imageFile, statusElement) {
  const uploadUrl = editorElement.dataset.richTextImageUploadUrl
  const expectedVersion = editorElement.dataset.richTextImageTicketVersion
  const csrfToken = formElement.querySelector('input[name="csrf_token"]')?.value
  if (!uploadUrl || !expectedVersion || !csrfToken) {
    statusElement.textContent = '이미지 업로드 정보를 확인할 수 없습니다.'
    statusElement.classList.add('is-error')
    return
  }
  if (activeImageUploadUrls.has(uploadUrl)) {
    statusElement.textContent = '이 티켓의 다른 이미지 업로드가 끝날 때까지 기다려 주세요.'
    statusElement.classList.add('is-error')
    return
  }

  activeImageUploadUrls.add(uploadUrl)
  setImageUploadButtonsDisabled(uploadUrl, true)
  statusElement.textContent = '이미지를 업로드하고 있습니다.'
  statusElement.classList.remove('is-error')
  const uploadPayload = new FormData()
  uploadPayload.append('expected_version', expectedVersion)
  uploadPayload.append('file', imageFile)

  try {
    const response = await fetch(uploadUrl, {
      method: 'POST',
      body: uploadPayload,
      credentials: 'same-origin',
      headers: { 'X-CSRF-Token': csrfToken },
    })
    const responsePayload = await response.json()
    if (!response.ok) {
      throw new Error(responsePayload.message || '이미지를 업로드하지 못했습니다.')
    }
    editor
      .chain()
      .focus()
      .insertContent({
        type: 'image',
        attrs: {
          attachmentId: responsePayload.attachment.id,
          alt: responsePayload.attachment.original_filename,
          title: responsePayload.attachment.original_filename,
        },
      })
      .run()
    updateTicketVersion(uploadUrl, responsePayload.ticket_version)
    statusElement.textContent = '이미지를 업로드하고 본문에 삽입했습니다.'
  } catch (error) {
    statusElement.textContent = error instanceof Error
      ? error.message
      : '이미지를 업로드하지 못했습니다.'
    statusElement.classList.add('is-error')
  } finally {
    activeImageUploadUrls.delete(uploadUrl)
    setImageUploadButtonsDisabled(uploadUrl, false)
  }
}

/** 단일 form 안의 Tiptap editor와 가장 가까운 payload·toolbar를 연결한다. */
function initializeEditor(editorElement) {
  const formElement = editorElement.closest('form')
  const fieldElement = editorElement.closest('.rich-text-field')
  const payloadElement = fieldElement?.querySelector('[data-rich-text-payload]')
  const toolbarElement = fieldElement?.querySelector('[data-rich-text-toolbar]')
  const imageInputElement = fieldElement?.querySelector('[data-rich-text-image-input]')
  const imageStatusElement = fieldElement?.querySelector('[data-rich-text-image-status]')
  if (!formElement || !payloadElement || !toolbarElement) return

  const accessibleLabel = editorElement.dataset.richTextLabel || '구조화 본문 편집기'
  const placeholder = editorElement.dataset.richTextPlaceholder || ''
  const editorAttributes = {
    class: 'tiptap-body',
    'aria-label': accessibleLabel,
  }
  if (placeholder) {
    editorAttributes['aria-placeholder'] = placeholder
    editorAttributes['data-placeholder'] = placeholder
  }

  const editor = new Editor({
    element: editorElement,
    content: readInitialDocument(payloadElement),
    enableInputRules: false,
    enablePasteRules: false,
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        horizontalRule: false,
        link: {
          openOnClick: false,
          autolink: true,
          defaultProtocol: 'https',
          protocols: ['http', 'https'],
        },
      }),
      TextStyle,
      Color.configure({ types: ['textStyle'] }),
      FontSize.configure({ types: ['textStyle'] }),
      TaskList,
      TaskItem.configure({ nested: true }),
      TableKit.configure({ table: { resizable: false } }),
      AttachmentImage,
    ],
    editorProps: {
      attributes: editorAttributes,
    },
    onCreate: ({ editor: currentEditor }) => {
      synchronizePayload(currentEditor, payloadElement)
      updateToolbarState(currentEditor, toolbarElement)
    },
    onSelectionUpdate: ({ editor: currentEditor }) => {
      updateToolbarState(currentEditor, toolbarElement)
    },
    onUpdate: ({ editor: currentEditor }) => {
      synchronizePayload(currentEditor, payloadElement)
      updateToolbarState(currentEditor, toolbarElement)
    },
  })
  const openLinkDialog = initializeLinkDialog(editor, fieldElement)

  fieldElement.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-rich-text-command]')
    if (!button) return
    if (button.dataset.richTextCommand === 'uploadImage') {
      imageInputElement?.click()
      return
    }
    if (button.dataset.richTextCommand === 'link') {
      openLinkDialog?.()
      return
    }
    executeButtonCommand(editor, button.dataset.richTextCommand)
  })
  fieldElement.addEventListener('change', (event) => {
    const imageInput = event.target.closest('[data-rich-text-image-input]')
    if (imageInput) {
      const [imageFile] = imageInput.files
      if (imageFile && imageStatusElement) {
        const shouldUploadImage = window.confirm('이미지를 첨부파일로 등록하시겠습니까?')
        if (shouldUploadImage) {
          uploadEditorImage(editor, editorElement, formElement, imageFile, imageStatusElement)
        }
      }
      imageInput.value = ''
      return
    }
    const select = event.target.closest('select[data-rich-text-command]')
    if (!select) return
    executeSelectCommand(editor, select.dataset.richTextCommand, select.value)
  })
  formElement.addEventListener('submit', (event) => {
    const uploadUrl = editorElement.dataset.richTextImageUploadUrl
    if (uploadUrl && activeImageUploadUrls.has(uploadUrl)) {
      event.preventDefault()
      if (imageStatusElement) {
        imageStatusElement.textContent = '이미지 업로드가 끝난 뒤 저장해 주세요.'
        imageStatusElement.classList.add('is-error')
      }
      return
    }
    synchronizePayload(editor, payloadElement)
  })
}

for (const editorElement of document.querySelectorAll('[data-rich-text-editor]')) {
  initializeEditor(editorElement)
}
