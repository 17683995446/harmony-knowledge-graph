/**
 * Harmony Knowledge Graph - 主JavaScript文件
 * 通用功能和工具函数
 */

// 全局配置
const CONFIG = {
    API_BASE_URL: '/api',
    DEFAULT_PAGE_SIZE: 100,
    MAX_RETRY: 3,
    RETRY_DELAY: 1000
};

// 工具函数
const Utils = {
    /**
     * 格式化数字
     */
    formatNumber(num) {
        if (num === null || num === undefined) return '-';
        return num.toLocaleString('zh-CN');
    },

    /**
     * 格式化文件大小
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    /**
     * 格式化时间
     */
    formatTime(seconds) {
        if (seconds < 60) {
            return Math.round(seconds) + '秒';
        } else if (seconds < 3600) {
            return Math.round(seconds / 60) + '分钟';
        } else {
            return Math.round(seconds / 3600 * 10) / 10 + '小时';
        }
    },

    /**
     * 防抖函数
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * 节流函数
     */
    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    /**
     * 深拷贝
     */
    deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    },

    /**
     * 生成唯一ID
     */
    generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2);
    },

    /**
     * 截断文本
     */
    truncate(text, maxLength = 100) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    },

    /**
     * 高亮关键词
     */
    highlight(text, keyword) {
        if (!keyword || !text) return text;
        const regex = new RegExp(`(${keyword})`, 'gi');
        return text.replace(regex, '<mark>$1</mark>');
    }
};

// API请求封装
const API = {
    /**
     * GET请求
     */
    async get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = `${CONFIG.API_BASE_URL}${endpoint}${queryString ? '?' + queryString : ''}`;
        
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    },

    /**
     * POST请求
     */
    async post(endpoint, data = {}) {
        const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    },

    /**
     * 带重试的请求
     */
    async requestWithRetry(requestFunc, maxRetry = CONFIG.MAX_RETRY) {
        let lastError;
        
        for (let i = 0; i < maxRetry; i++) {
            try {
                return await requestFunc();
            } catch (error) {
                lastError = error;
                if (i < maxRetry - 1) {
                    await new Promise(resolve => setTimeout(resolve, CONFIG.RETRY_DELAY * (i + 1)));
                }
            }
        }
        
        throw lastError;
    }
};

// UI组件
const UI = {
    /**
     * 显示加载状态
     */
    showLoading(element, message = '加载中...') {
        element.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <div class="loading" style="width: 40px; height: 40px; margin: 0 auto 16px;"></div>
                <p style="color: var(--text-secondary);">${message}</p>
            </div>
        `;
    },

    /**
     * 显示错误信息
     */
    showError(element, message) {
        element.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <i class="fas fa-exclamation-circle" style="font-size: 48px; color: var(--danger-color); margin-bottom: 16px;"></i>
                <p style="color: var(--text-secondary);">${message}</p>
            </div>
        `;
    },

    /**
     * 显示空状态
     */
    showEmpty(element, message = '暂无数据') {
        element.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <i class="fas fa-inbox" style="font-size: 48px; color: var(--text-secondary); margin-bottom: 16px;"></i>
                <p style="color: var(--text-secondary);">${message}</p>
            </div>
        `;
    },

    /**
     * 创建表格
     */
    createTable(data, columns, options = {}) {
        const table = document.createElement('table');
        table.className = 'results-table';

        // 表头
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        
        columns.forEach(col => {
            const th = document.createElement('th');
            th.textContent = col.label || col.key;
            if (col.width) {
                th.style.width = col.width;
            }
            headerRow.appendChild(th);
        });
        
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // 表体
        const tbody = document.createElement('tbody');
        
        data.forEach((row, index) => {
            const tr = document.createElement('tr');
            
            columns.forEach(col => {
                const td = document.createElement('td');
                let value = row[col.key];
                
                // 格式化
                if (col.format) {
                    value = col.format(value, row);
                }
                
                // 渲染
                if (col.render) {
                    td.innerHTML = col.render(value, row, index);
                } else {
                    td.textContent = value !== null && value !== undefined ? value : '-';
                }
                
                tr.appendChild(td);
            });
            
            // 行点击事件
            if (options.onRowClick) {
                tr.style.cursor = 'pointer';
                tr.addEventListener('click', () => options.onRowClick(row, index));
            }
            
            tbody.appendChild(tr);
        });
        
        table.appendChild(tbody);
        return table;
    },

    /**
     * 创建分页
     */
    createPagination(total, pageSize, currentPage, onPageChange) {
        const totalPages = Math.ceil(total / pageSize);
        const container = document.createElement('div');
        container.style.cssText = 'display: flex; justify-content: center; align-items: center; gap: 8px; padding: 16px;';

        // 上一页
        const prevBtn = document.createElement('button');
        prevBtn.className = 'btn btn-secondary';
        prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
        prevBtn.disabled = currentPage <= 1;
        prevBtn.onclick = () => onPageChange(currentPage - 1);
        container.appendChild(prevBtn);

        // 页码
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);
        
        for (let i = startPage; i <= endPage; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.className = i === currentPage ? 'btn btn-primary' : 'btn btn-secondary';
            pageBtn.textContent = i;
            pageBtn.onclick = () => onPageChange(i);
            container.appendChild(pageBtn);
        }

        // 下一页
        const nextBtn = document.createElement('button');
        nextBtn.className = 'btn btn-secondary';
        nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
        nextBtn.disabled = currentPage >= totalPages;
        nextBtn.onclick = () => onPageChange(currentPage + 1);
        container.appendChild(nextBtn);

        // 统计信息
        const info = document.createElement('span');
        info.style.cssText = 'color: var(--text-secondary); font-size: 13px; margin-left: 16px;';
        info.textContent = `共 ${total} 条，${totalPages} 页`;
        container.appendChild(info);

        return container;
    },

    /**
     * 显示Toast提示
     */
    toast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 24px;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            z-index: 9999;
            animation: slideIn 0.3s ease;
        `;

        const colors = {
            success: '#10b981',
            error: '#ef4444',
            warning: '#f59e0b',
            info: '#3b82f6'
        };

        toast.style.backgroundColor = colors[type] || colors.info;
        toast.textContent = message;

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
};

// 本地存储封装
const Storage = {
    /**
     * 设置值
     */
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            console.error('Storage set error:', e);
        }
    },

    /**
     * 获取值
     */
    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (e) {
            console.error('Storage get error:', e);
            return defaultValue;
        }
    },

    /**
     * 删除值
     */
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.error('Storage remove error:', e);
        }
    },

    /**
     * 清空
     */
    clear() {
        try {
            localStorage.clear();
        } catch (e) {
            console.error('Storage clear error:', e);
        }
    }
};

// 事件总线
const EventBus = {
    events: {},

    on(event, callback) {
        if (!this.events[event]) {
            this.events[event] = [];
        }
        this.events[event].push(callback);
    },

    off(event, callback) {
        if (!this.events[event]) return;
        this.events[event] = this.events[event].filter(cb => cb !== callback);
    },

    emit(event, data) {
        if (!this.events[event]) return;
        this.events[event].forEach(callback => callback(data));
    }
};

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 导出
window.Utils = Utils;
window.API = API;
window.UI = UI;
window.Storage = Storage;
window.EventBus = EventBus;
window.CONFIG = CONFIG;
