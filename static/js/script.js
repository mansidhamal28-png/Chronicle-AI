// Chronicle AI - Frontend Interactions & Dynamic State Management

document.addEventListener('DOMContentLoaded', () => {
    initDropzone();
    initChatInterface();
    initNotesFilter();
    initTimelineFilter();
    initCopyButtons();
});

// ---------------- FILE UPLOAD & DROPZONE ---------------- //
function initDropzone() {
    const dropzone = document.getElementById('uploadDropzone');
    const fileInput = document.getElementById('documentFileInput');
    const uploadForm = document.getElementById('documentUploadForm');
    const fileDetailsBox = document.getElementById('selectedFileInfo');
    const selectedFileName = document.getElementById('selectedFileName');
    const selectedFileSize = document.getElementById('selectedFileSize');
    const submitBtn = document.getElementById('btnStartProcessing');
    const uploadLoadingOverlay = document.getElementById('uploadLoadingOverlay');

    if (!dropzone || !fileInput) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            fileInput.files = files;
            displaySelectedFile(files[0]);
        }
    });

    dropzone.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files.length > 0) {
            displaySelectedFile(fileInput.files[0]);
        }
    });

    function displaySelectedFile(file) {
        if (fileDetailsBox) {
            fileDetailsBox.classList.remove('d-none');
        }
        if (selectedFileName) selectedFileName.textContent = file.name;
        if (selectedFileSize) {
            const sizeInMb = (file.size / (1024 * 1024)).toFixed(2);
            selectedFileSize.textContent = `${sizeInMb} MB`;
        }
        if (submitBtn) {
            submitBtn.removeAttribute('disabled');
        }
    }

    if (uploadForm) {
        uploadForm.addEventListener('submit', () => {
            if (uploadLoadingOverlay) {
                uploadLoadingOverlay.classList.remove('d-none');
            }
            if (submitBtn) {
                submitBtn.setAttribute('disabled', 'true');
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Analyzing Document with AI...';
            }
        });
    }
}

// ---------------- INTELLIGENT CHAT INTERFACE ---------------- //
function initChatInterface() {
    const chatContainer = document.getElementById('chatMessages');
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('chatSendBtn');
    const docIdField = document.getElementById('chatDocumentId');
    const clearChatBtn = document.getElementById('clearChatBtn');

    if (!chatInput || !sendBtn) return;

    // Scroll to bottom of chat
    scrollToChatBottom();

    // Send message on Enter (without Shift)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', (e) => {
        e.preventDefault();
        sendMessage();
    });

    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', async () => {
            if (!confirm('Are you sure you want to clear this conversation history?')) return;
            const docId = docIdField ? docIdField.value : '';
            try {
                const res = await fetch('/api/chat/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ document_id: docId })
                });
                const data = await res.json();
                if (data.success) {
                    if (chatContainer) {
                        chatContainer.innerHTML = `
                            <div class="text-center text-muted py-5" id="chatEmptyState">
                                <i class="bi bi-chat-dots fs-1 d-block mb-3 opacity-50"></i>
                                <p class="mb-1 fw-semibold text-white">Conversation cleared</p>
                                <p class="small">Ask anything about your document to start a new inquiry.</p>
                            </div>
                        `;
                    }
                }
            } catch (err) {
                console.error('Error clearing chat:', err);
            }
        });
    }

    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        const docId = docIdField ? docIdField.value : '';

        // Remove empty state placeholder if present
        const emptyState = document.getElementById('chatEmptyState');
        if (emptyState) emptyState.remove();

        // Append user message immediately
        appendMessage('user', text);
        chatInput.value = '';
        chatInput.style.height = 'auto';

        // Show typing indicator
        const typingId = 'typingIndicator_' + Date.now();
        appendTypingIndicator(typingId);
        scrollToChatBottom();

        // Disable input while generating
        sendBtn.disabled = true;
        chatInput.disabled = true;

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    document_id: docId
                })
            });

            removeTypingIndicator(typingId);

            if (!response.ok) {
                throw new Error(`Server returned status ${response.status}`);
            }

            const data = await response.json();
            if (data.success) {
                appendMessage('assistant', data.answer, data.sources);
            } else {
                appendMessage('assistant', `Error: ${data.error || 'Failed to process inquiry.'}`);
            }
        } catch (error) {
            removeTypingIndicator(typingId);
            appendMessage('assistant', `Network or system error: ${error.message}. Please check connection.`);
        } finally {
            sendBtn.disabled = false;
            chatInput.disabled = false;
            chatInput.focus();
            scrollToChatBottom();
        }
    }

    function appendMessage(role, content, sources) {
        if (!chatContainer) return;
        const msgWrapper = document.createElement('div');
        msgWrapper.className = `chat-msg ${role}`;

        let formattedContent = escapeHtml(content)
            .replace(/\n\n/g, '<br><br>')
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code class="bg-dark px-1 rounded text-cyan">$1</code>');

        let sourcesHtml = '';
        if (sources && sources.length > 0) {
            sourcesHtml = `<div class="mt-2 pt-2 border-top border-secondary border-opacity-25 small text-info opacity-75">
                <i class="bi bi-bookmark-check me-1"></i> ${sources.join(', ')}
            </div>`;
        }

        const roleAvatar = role === 'user' 
            ? '<i class="bi bi-person-fill"></i>' 
            : '<i class="bi bi-stars text-cyan"></i>';

        msgWrapper.innerHTML = `
            <div class="d-flex align-items-center gap-2 mb-1 ${role === 'user' ? 'justify-content-end text-muted' : 'text-info'} small">
                <span>${roleAvatar}</span>
                <span class="fw-semibold">${role === 'user' ? 'You' : 'Chronicle AI'}</span>
            </div>
            <div class="msg-bubble">
                ${formattedContent}
                ${sourcesHtml}
            </div>
        `;
        chatContainer.appendChild(msgWrapper);
    }

    function appendTypingIndicator(id) {
        if (!chatContainer) return;
        const typingEl = document.createElement('div');
        typingEl.id = id;
        typingEl.className = 'chat-msg assistant';
        typingEl.innerHTML = `
            <div class="d-flex align-items-center gap-2 mb-1 text-info small">
                <i class="bi bi-stars"></i>
                <span class="fw-semibold">Chronicle AI</span>
            </div>
            <div class="msg-bubble d-flex align-items-center gap-2 py-3">
                <div class="spinner-grow spinner-grow-sm text-primary" role="status"></div>
                <div class="spinner-grow spinner-grow-sm text-info" role="status"></div>
                <div class="spinner-grow spinner-grow-sm text-light" role="status"></div>
                <span class="small text-muted ms-1">Consulting knowledge base...</span>
            </div>
        `;
        chatContainer.appendChild(typingEl);
    }

    function removeTypingIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function scrollToChatBottom() {
        if (chatContainer) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }
}

// ---------------- SMART NOTES FILTERING & SEARCH ---------------- //
function initNotesFilter() {
    const categoryFilter = document.getElementById('noteCategoryFilter');
    const noteSearchInput = document.getElementById('noteSearchInput');
    const noteCards = document.querySelectorAll('.note-card-item');

    if (!noteCards.length) return;

    function applyFilter() {
        const selectedCat = categoryFilter ? categoryFilter.value.toLowerCase() : 'all';
        const searchTerm = noteSearchInput ? noteSearchInput.value.toLowerCase().trim() : '';

        noteCards.forEach(card => {
            const cardCat = (card.getAttribute('data-category') || '').toLowerCase();
            const cardText = card.textContent.toLowerCase();

            const matchCat = (selectedCat === 'all' || cardCat === selectedCat);
            const matchSearch = (!searchTerm || cardText.includes(searchTerm));

            if (matchCat && matchSearch) {
                card.classList.remove('d-none');
            } else {
                card.classList.add('d-none');
            }
        });
    }

    if (categoryFilter) categoryFilter.addEventListener('change', applyFilter);
    if (noteSearchInput) noteSearchInput.addEventListener('input', applyFilter);
}

// ---------------- TIMELINE FILTERING ---------------- //
function initTimelineFilter() {
    const docFilter = document.getElementById('timelineDocFilter');
    const searchFilter = document.getElementById('timelineSearchInput');
    const timelineItems = document.querySelectorAll('.timeline-item');

    if (!timelineItems.length) return;

    function applyTimelineFilter() {
        const selectedDoc = docFilter ? docFilter.value : 'all';
        const searchTerm = searchFilter ? searchFilter.value.toLowerCase().trim() : '';

        timelineItems.forEach(item => {
            const itemDoc = item.getAttribute('data-doc-id') || '';
            const itemText = item.textContent.toLowerCase();

            const matchDoc = (selectedDoc === 'all' || itemDoc === selectedDoc);
            const matchSearch = (!searchTerm || itemText.includes(searchTerm));

            if (matchDoc && matchSearch) {
                item.classList.remove('d-none');
            } else {
                item.classList.add('d-none');
            }
        });
    }

    if (docFilter) docFilter.addEventListener('change', applyTimelineFilter);
    if (searchFilter) searchFilter.addEventListener('input', applyTimelineFilter);
}

// ---------------- COPY TO CLIPBOARD BUTTONS ---------------- //
function initCopyButtons() {
    document.querySelectorAll('.btn-copy-clipboard').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const targetEl = document.getElementById(targetId);
            if (!targetEl) return;

            const text = targetEl.innerText || targetEl.textContent;
            navigator.clipboard.writeText(text).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-check-lg text-success"></i> Copied!';
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy text: ', err);
            });
        });
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
