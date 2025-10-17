document.addEventListener('DOMContentLoaded', () => {
    // --- Global State ---
    let currentConversationId = null;

    // --- Element Selectors ---
    const chatBox = document.getElementById('chat-box');
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const conversationHistory = document.getElementById('conversation-history');
    const suggestionsContainer = document.getElementById('suggestions-container');
    const typingIndicator = document.getElementById('typing-indicator');
    const chatTitle = document.getElementById('chat-title');
    const themeToggle = document.getElementById('theme-toggle');
    
    // Share and Export Elements
    const shareChatBtn = document.getElementById('share-chat-btn');
    const exportMenuBtn = document.getElementById('export-menu-btn');
    const exportOptions = document.getElementById('export-options');
    const shareModal = document.getElementById('share-modal');
    const shareLinkInput = document.getElementById('share-link-input');
    const copyLinkBtn = document.getElementById('copy-link-btn');
    const closeModalBtn = document.getElementById('close-modal-btn');


    // --- Theme Management ---
    const applyTheme = (theme) => {
        document.documentElement.className = theme;
        localStorage.setItem('theme', theme);
        if(themeToggle) themeToggle.checked = theme === 'dark';
    };

    if(themeToggle) {
        themeToggle.addEventListener('change', () => {
            applyTheme(themeToggle.checked ? 'dark' : 'light');
        });
    }

    // --- UI Update Functions ---
    const showTypingIndicator = (show) => {
        if(typingIndicator) typingIndicator.style.display = show ? 'flex' : 'none';
        if (show && chatBox) chatBox.scrollTop = chatBox.scrollHeight;
    };

    const addMessageToUI = (message, sender) => {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender === 'user' ? 'user-message' : (sender === 'model' ? 'bot-message' : ''));
        // Use marked.parse to render markdown content
        messageElement.innerHTML = marked.parse(message);
        chatBox.appendChild(messageElement);
        chatBox.scrollTop = chatBox.scrollHeight;
    };

    const resetChatArea = () => {
        chatBox.innerHTML = '';
        if (suggestionsContainer) {
            chatBox.appendChild(suggestionsContainer);
            suggestionsContainer.style.display = 'flex';
        }
        chatTitle.textContent = 'New Chat';
        if(shareChatBtn) shareChatBtn.style.display = 'none';
        if(exportMenuBtn) exportMenuBtn.style.display = 'none';
    };

    // --- API Interaction ---
    const sendMessage = async (message) => {
        if (!message) return;
        if (suggestionsContainer) suggestionsContainer.style.display = 'none';
        addMessageToUI(message, 'user');
        showTypingIndicator(true);

        try {
            if (!currentConversationId) {
                const response = await fetch('/new_conversation', { method: 'POST' });
                const data = await response.json();
                if (data.error) throw new Error(data.error);
                currentConversationId = data.conversation_id;
                window.history.pushState({}, '', `/conversation/${currentConversationId}`);
                await loadConversationHistory(); // Refresh history
            }

            const response = await fetch(`/conversations/${currentConversationId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            
            addMessageToUI(data.response, 'model');
            await loadConversationHistory(); // To update title if it was generated

        } catch (error) {
            addMessageToUI(`Error: ${error.message}`, 'model');
        } finally {
            showTypingIndicator(false);
        }
    };

    const loadConversation = async (convId) => {
        if (!convId) {
            resetChatArea();
            currentConversationId = null;
            window.history.pushState({}, '', '/');
            return;
        }
        try {
            const response = await fetch(`/conversations/${convId}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            chatBox.innerHTML = '';
            if (suggestionsContainer) suggestionsContainer.style.display = 'none';
            data.messages.forEach(msg => addMessageToUI(msg.content, msg.sender));
            
            chatTitle.textContent = data.title;
            currentConversationId = convId;
            if(shareChatBtn) shareChatBtn.style.display = 'flex';
            if(exportMenuBtn) exportMenuBtn.style.display = 'flex';

            window.history.pushState({}, '', `/conversation/${convId}`);
            document.querySelectorAll('.conversation-link').forEach(link => {
                link.classList.toggle('active', link.dataset.id == convId);
            });

        } catch (error) {
            console.error('Failed to load conversation:', error);
            resetChatArea();
        }
    };

    const loadConversationHistory = async () => {
        if (!conversationHistory) return;
        try {
            const response = await fetch('/conversations');
            const conversations = await response.json();
            conversationHistory.innerHTML = '';
            conversations.forEach(conv => {
                const link = document.createElement('a');
                link.href = `/conversation/${conv.id}`;
                link.className = 'conversation-link';
                link.textContent = conv.title;
                link.dataset.id = conv.id;
                if (conv.id == currentConversationId) {
                    link.classList.add('active');
                    if (chatTitle) chatTitle.textContent = conv.title;
                }
                conversationHistory.appendChild(link);
            });
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    };
    
    const handleShare = async () => {
        if (!currentConversationId) return;
        try {
            const response = await fetch(`/conversations/${currentConversationId}/share`, { method: 'POST' });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            
            shareLinkInput.value = data.share_url;
            shareModal.style.display = 'flex';

        } catch(error) {
            alert(`Could not share chat: ${error.message}`);
        }
    };

    // --- Event Listeners ---
    if (messageForm) {
        messageForm.addEventListener('submit', (e) => {
            e.preventDefault();
            sendMessage(messageInput.value.trim());
            messageInput.value = '';
            messageInput.style.height = 'auto';
        });
    }
    
    if (suggestionsContainer) {
        suggestionsContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('suggestion-chip')) {
                sendMessage(e.target.textContent);
            }
        });
    }

    if (conversationHistory) {
        conversationHistory.addEventListener('click', (e) => {
            e.preventDefault();
            const link = e.target.closest('.conversation-link');
            if (link) {
                loadConversation(link.dataset.id);
            }
        });
    }

    if (messageInput) {
        messageInput.addEventListener('input', () => {
            messageInput.style.height = 'auto';
            messageInput.style.height = (messageInput.scrollHeight) + 'px';
        });
    }
    
    if(shareChatBtn) shareChatBtn.addEventListener('click', handleShare);
    if(closeModalBtn) closeModalBtn.addEventListener('click', () => shareModal.style.display = 'none');
    if(copyLinkBtn) {
        copyLinkBtn.addEventListener('click', () => {
            shareLinkInput.select();
            document.execCommand('copy');
            copyLinkBtn.innerHTML = '<span class="material-symbols-outlined">done</span>';
            setTimeout(() => {
                copyLinkBtn.innerHTML = '<span class="material-symbols-outlined">content_copy</span>';
            }, 2000);
        });
    }
    if(exportMenuBtn) {
        exportMenuBtn.addEventListener('click', () => {
            exportOptions.classList.toggle('visible');
        });
    }
    if(exportOptions) {
        exportOptions.addEventListener('click', (e) => {
            e.preventDefault();
            if(e.target.tagName === 'A' && currentConversationId) {
                const format = e.target.dataset.format;
                window.location.href = `/conversations/${currentConversationId}/export?format=${format}`;
                exportOptions.classList.remove('visible');
            }
        });
    }
    document.addEventListener('click', (e) => {
        if (exportMenuBtn && !exportMenuBtn.contains(e.target) && exportOptions && !exportOptions.contains(e.target)) {
            exportOptions.classList.remove('visible');
        }
    });

    // --- Initial Load ---
    const init = () => {
        const savedTheme = localStorage.getItem('theme') || 'dark';
        applyTheme(savedTheme);

        if (document.querySelector('.app-layout')) {
            document.body.classList.add('chat-page');
            const path = window.location.pathname;
            const match = path.match(/\/conversation\/(\d+)/);
            const convId = match ? match[1] : null;
            
            loadConversation(convId);
            loadConversationHistory();
        }
    };

    init();
});
