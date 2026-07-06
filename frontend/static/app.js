// ================================================================
// AuraFactory — Shared JS Utilities
// ================================================================

/**
 * Debounce function — delay execution until user stops triggering.
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Delay in milliseconds
 */
function debounce(fn, delay = 300) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

/**
 * Format timestamp to Vietnamese locale.
 * @param {string|number} ts - ISO string or Unix timestamp
 * @returns {string} Formatted date string
 */
function formatTimestamp(ts) {
    const date = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    return date.toLocaleString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/**
 * Show a toast notification.
 * @param {string} message - Message to display
 * @param {string} type - 'success' | 'error' | 'info'
 * @param {number} duration - Duration in ms (default 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    // Style
    Object.assign(toast.style, {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        padding: '12px 20px',
        borderRadius: '8px',
        color: '#fff',
        fontSize: '0.85rem',
        fontWeight: '500',
        zIndex: '9999',
        opacity: '0',
        transform: 'translateY(10px)',
        transition: 'all 0.3s ease',
        maxWidth: '320px',
    });

    const colors = {
        success: '#43b581',
        error: '#f04747',
        info: '#7289da',
    };
    toast.style.background = colors[type] || colors.info;

    document.body.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
    });

    // Remove after duration
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Fetch wrapper with error handling.
 * @param {string} url - API URL
 * @param {object} options - Fetch options
 * @returns {Promise<object>} Parsed JSON response
 */
async function apiFetch(url, options = {}) {
    const defaults = {
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
    };

    const config = { ...defaults, ...options };
    if (options.headers) {
        config.headers = { ...defaults.headers, ...options.headers };
    }

    try {
        const response = await fetch(url, config);

        if (response.status === 401) {
            window.location.href = '/';
            return null;
        }

        if (response.status === 429) {
            showToast('Bạn đang gửi quá nhanh. Vui lòng đợi.', 'error');
            return null;
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (e) {
        if (e.name === 'TypeError') {
            showToast('Lỗi kết nối mạng.', 'error');
        }
        throw e;
    }
}

/**
 * Copy text to clipboard.
 * @param {string} text - Text to copy
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Đã sao chép!', 'success', 2000);
    } catch {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        textarea.remove();
        showToast('Đã sao chép!', 'success', 2000);
    }
}

/**
 * Simple local storage wrapper with JSON support.
 */
const storage = {
    get(key, fallback = null) {
        try {
            const val = localStorage.getItem(`aurafactory_${key}`);
            return val ? JSON.parse(val) : fallback;
        } catch {
            return fallback;
        }
    },
    set(key, value) {
        try {
            localStorage.setItem(`aurafactory_${key}`, JSON.stringify(value));
        } catch {
            // Storage full or unavailable
        }
    },
    remove(key) {
        localStorage.removeItem(`aurafactory_${key}`);
    },
};
