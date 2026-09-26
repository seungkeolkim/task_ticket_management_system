import { Editor, Node } from '@tiptap/core'
import Color from '@tiptap/extension-color'
import { TableKit } from '@tiptap/extension-table'
import TaskItem from '@tiptap/extension-task-item'
import TaskList from '@tiptap/extension-task-list'
import { FontSize, TextStyle } from '@tiptap/extension-text-style'
import StarterKit from '@tiptap/starter-kit'

const EMPTY_DOCUMENT = { type: 'doc', content: [{ type: 'paragraph' }] }

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
  if (commandName === 'link') {
    const currentUrl = editor.getAttributes('link').href || ''
    const requestedUrl = window.prompt('연결할 http(s) 또는 내부 경로를 입력하세요.', currentUrl)
    if (requestedUrl === null) return
    if (!requestedUrl.trim()) {
      editor.chain().focus().extendMarkRange('link').unsetLink().run()
      return
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: requestedUrl.trim() }).run()
    return
  }
  commands[commandName]?.()
}

/** 단일 ticket form에 Tiptap editor와 toolbar를 연결한다. */
function initializeEditor(editorElement) {
  const formElement = editorElement.closest('form')
  const fieldElement = editorElement.closest('.rich-text-field')
  const payloadElement = fieldElement?.querySelector('[data-rich-text-payload]')
  const toolbarElement = fieldElement?.querySelector('[data-rich-text-toolbar]')
  if (!formElement || !payloadElement || !toolbarElement) return

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
          autolink: false,
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
      attributes: {
        class: 'tiptap-body',
        'aria-label': '티켓 설명 편집기',
      },
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

  fieldElement.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-rich-text-command]')
    if (!button) return
    executeButtonCommand(editor, button.dataset.richTextCommand)
  })
  fieldElement.addEventListener('change', (event) => {
    const select = event.target.closest('select[data-rich-text-command]')
    if (!select) return
    executeSelectCommand(editor, select.dataset.richTextCommand, select.value)
  })
  formElement.addEventListener('submit', () => synchronizePayload(editor, payloadElement))
}

for (const editorElement of document.querySelectorAll('[data-rich-text-editor]')) {
  initializeEditor(editorElement)
}
