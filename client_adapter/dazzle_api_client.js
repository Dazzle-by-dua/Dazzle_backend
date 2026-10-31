/* ==========================================================================
   DAZZLE BY DUA ? Production API Client & DazzleStore Bridge
   Seamless drop-in replacement / API connector for DazzleStore
   Enables 100% Admin -> API -> Database -> Storefront synchronization
   ========================================================================== */

(function (root, factory) {
  if (typeof define === "function" && define.amd) {
    define([], factory);
  } else if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.DazzleApi = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const API_BASE_URL = "https://dazzle-backend-69un.onrender.com";

  // Default API configuration
  const API_CONFIG = {
    BASE_URL: API_BASE_URL,
    STORAGE_AUTH_KEY: "dazzle_admin_session",
    STORAGE_CUSTOMER_KEY: "dazzle_customer_session",
    TIMEOUT_MS: 10000
  };

  /**
   * Helper to retrieve active JWT token from CustomerAuth or Storage
   */
  function getCustomerToken() {
    try {
      const sessStr = sessionStorage.getItem(API_CONFIG.STORAGE_CUSTOMER_KEY) || localStorage.getItem(API_CONFIG.STORAGE_CUSTOMER_KEY);
      if (sessStr) {
        const sess = JSON.parse(sessStr);
        return sess.token || null;
      }
    } catch (e) {
      console.warn("Could not read customer auth session:", e);
    }
    return null;
  }

  /**
   * Helper to retrieve active JWT token from AdminAuth or Storage
   */
  function getAuthToken() {
    try {
      const sessStr = localStorage.getItem(API_CONFIG.STORAGE_AUTH_KEY) || sessionStorage.getItem(API_CONFIG.STORAGE_AUTH_KEY);
      if (sessStr) {
        const sess = JSON.parse(sessStr);
        return sess.token || null;
      }
    } catch (e) {
      console.warn("Could not read auth session:", e);
    }
    return null;
  }

  /**
   * Core HTTP request handler
   */
  async function request(endpoint, options = {}) {
    const url = endpoint.startsWith("http") ? endpoint : `${API_CONFIG.BASE_URL}${endpoint}`;
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {})
    };

    const adminToken = getAuthToken();
    const custToken = getCustomerToken();

    // Attach customer token for customer endpoints, review operations, or storefront user operations
    if (endpoint.includes("/api/customer/") || endpoint.includes("/api/reviews") || (custToken && !adminToken)) {
      if (custToken && !headers["Authorization"]) {
        headers["Authorization"] = `Bearer ${custToken}`;
      } else if (adminToken && !headers["Authorization"]) {
        headers["Authorization"] = `Bearer ${adminToken}`;
      }
    } else if (adminToken && !headers["Authorization"]) {
      headers["Authorization"] = `Bearer ${adminToken}`;
    }

    const fetchOptions = {
      ...options,
      headers,
      credentials: "include"
    };

    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      fetchOptions.body = JSON.stringify(options.body);
    }

    try {
      const response = await fetch(url, fetchOptions);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorData.detail || `Request failed with status ${response.status}`);
      }
      return await response.json();
    } catch (err) {
      console.error(`API Error on ${url}:`, err);
      throw err;
    }
  }

  // =========================================================================
  // Asynchronous API Services
  // =========================================================================
  const api = {
    config: API_CONFIG,

    // Authentication
    auth: {
      async login(username, password, rememberMe = false) {
        const res = await request("/api/auth/login", {
          method: "POST",
          body: { username, password, rememberMe }
        });
        if (res && res.token) {
          const sessionData = {
            user: res.user.user,
            email: res.user.email,
            role: res.user.role,
            token: res.token,
            loginTime: res.loginTime
          };
          if (rememberMe) {
            localStorage.setItem(API_CONFIG.STORAGE_AUTH_KEY, JSON.stringify(sessionData));
          } else {
            sessionStorage.setItem(API_CONFIG.STORAGE_AUTH_KEY, JSON.stringify(sessionData));
          }
        }
        return res;
      },
      async me() {
        return await request("/api/auth/me");
      },
      async logout() {
        localStorage.removeItem(API_CONFIG.STORAGE_AUTH_KEY);
        sessionStorage.removeItem(API_CONFIG.STORAGE_AUTH_KEY);
        return await request("/api/auth/logout", { method: "POST" });
      }
    },

    // Products
    products: {
      async getAll(filters = {}) {
        const params = new URLSearchParams();
        if (filters.category) params.append("category", filters.category);
        if (filters.inStock !== undefined) params.append("inStock", filters.inStock);
        if (filters.search) params.append("search", filters.search);
        if (filters.sort) params.append("sort", filters.sort);
        const qs = params.toString() ? `?${params.toString()}` : "";
        return await request(`/api/products${qs}`);
      },
      async getById(id) {
        return await request(`/api/products/${id}`);
      },
      async create(product) {
        return await request("/api/products", { method: "POST", body: product });
      },
      async update(id, updates) {
        return await request(`/api/products/${id}`, { method: "PUT", body: updates });
      },
      async toggleStock(id, inStock) {
        return await request(`/api/products/${id}/stock`, { method: "PATCH", body: { inStock } });
      },
      async delete(id) {
        return await request(`/api/products/${id}`, { method: "DELETE" });
      },
      async getDetailsMap() {
        return await request("/api/products/details/map");
      }
    },

    // Categories
    categories: {
      async getAll() {
        return await request("/api/categories");
      },
      async getById(id) {
        return await request(`/api/categories/${id}`);
      },
      async create(category) {
        return await request("/api/categories", { method: "POST", body: category });
      },
      async update(id, updates) {
        return await request(`/api/categories/${id}`, { method: "PUT", body: updates });
      },
      async delete(id) {
        return await request(`/api/categories/${id}`, { method: "DELETE" });
      }
    },

    // Orders
    orders: {
      async getAll(filters = {}) {
        const params = new URLSearchParams();
        if (filters.status) params.append("status", filters.status);
        if (filters.search) params.append("search", filters.search);
        const qs = params.toString() ? `?${params.toString()}` : "";
        return await request(`/api/orders${qs}`);
      },
      async getById(id) {
        return await request(`/api/orders/${id}`);
      },
      /**
       * Get the currently authenticated customer's own orders.
       * Uses the customer JWT (cookie or Authorization header).
       * This is the primary My Orders data source — never use localStorage for this.
       */
      async getMyOrders() {
        const token = getCustomerToken();
        return await request("/api/customer/orders", {
          headers: token ? { "Authorization": `Bearer ${token}` } : {}
        });
      },
      async create(order) {
        return await request("/api/orders", { method: "POST", body: order });
      },
      async updateStatus(id, statusValue, paymentStatus) {
        const body = { status: statusValue };
        if (paymentStatus) body.paymentStatus = paymentStatus;
        return await request(`/api/orders/${id}/status`, { method: "PATCH", body });
      },
      async delete(id) {
        return await request(`/api/orders/${id}`, { method: "DELETE" });
      },
      async createRazorpayOrder(payload) {
        return await request("/api/orders/razorpay/create-order", { method: "POST", body: payload });
      },
      async verifyRazorpayPayment(payload) {
        return await request("/api/orders/razorpay/verify", { method: "POST", body: payload });
      },
      async recordPaymentFailure(payload) {
        return await request("/api/orders/razorpay/payment-failed", { method: "POST", body: payload });
      },
      async getPaymentStatus(orderId) {
        return await request(`/api/orders/${orderId}/payment-status`);
      },
      async getRazorpayConfig() {
        return await request("/api/orders/razorpay/config");
      }
    },


    // Customers
    customers: {
      async getAll() {
        return await request("/api/customers");
      },
      async getDetails(email) {
        return await request(`/api/customers/${encodeURIComponent(email)}`);
      }
    },

    // Reviews
    reviews: {
      async checkEligibility(productId) {
        return await request(`/api/reviews/eligibility?product_id=${encodeURIComponent(productId)}`);
      },
      async getAll(filters = {}) {
        const params = new URLSearchParams();
        if (filters.approvedOnly) params.append("approved_only", "true");
        if (filters.product) params.append("product", filters.product);
        const qs = params.toString() ? `?${params.toString()}` : "";
        return await request(`/api/reviews${qs}`);
      },
      async create(review) {
        return await request("/api/reviews", { method: "POST", body: review });
      },
      async update(id, updates) {
        return await request(`/api/reviews/${id}`, { method: "PUT", body: updates });
      },
      async toggleStatus(id, approved) {
        return await request(`/api/reviews/${id}/status`, { method: "PATCH", body: { approved } });
      },
      async delete(id) {
        return await request(`/api/reviews/${id}`, { method: "DELETE" });
      }
    },

    // Offers & Combos
    offers: {
      async getAll() {
        return await request("/api/offers");
      },
      async getCoupons() {
        return await request("/api/offers/coupons");
      },
      async createCoupon(coupon) {
        return await request("/api/offers/coupons", { method: "POST", body: coupon });
      },
      async updateCoupon(id, updates) {
        return await request(`/api/offers/coupons/${id}`, { method: "PUT", body: updates });
      },
      async deleteCoupon(id) {
        return await request(`/api/offers/coupons/${id}`, { method: "DELETE" });
      },
      async validateCoupon(code, orderTotal) {
        return await request("/api/offers/coupons/validate", {
          method: "POST",
          body: { code, orderTotal }
        });
      },
      async getCombos() {
        return await request("/api/offers/combos");
      },
      async createCombo(combo) {
        return await request("/api/offers/combos", { method: "POST", body: combo });
      },
      async updateCombo(id, updates) {
        return await request(`/api/offers/combos/${id}`, { method: "PUT", body: updates });
      },
      async deleteCombo(id) {
        return await request(`/api/offers/combos/${id}`, { method: "DELETE" });
      }
    },

    // Homepage
    homepage: {
      async get() {
        return await request("/api/homepage");
      },
      async update(config) {
        return await request("/api/homepage", { method: "PUT", body: config });
      },
      async updateSection(section, data) {
        return await request(`/api/homepage/${section}`, { method: "PATCH", body: data });
      }
    },

    // Settings
    settings: {
      async get() {
        return await request("/api/settings");
      },
      async update(settings) {
        return await request("/api/settings", { method: "PUT", body: settings });
      }
    },

    // Navigation
    navigation: {
      async get() {
        return await request("/api/navigation");
      },
      async update(navigation) {
        return await request("/api/navigation", { method: "PUT", body: navigation });
      },
      async addItem(section, item) {
        return await request(`/api/navigation/${section}`, { method: "POST", body: item });
      },
      async deleteItem(section, index) {
        return await request(`/api/navigation/${section}/${index}`, { method: "DELETE" });
      }
    },

    // Pages & Policies
    pages: {
      async get() {
        return await request("/api/pages");
      },
      async update(content) {
        return await request("/api/pages", { method: "PUT", body: content });
      }
    },

    // Media
    media: {
      async getAll() {
        return await request("/api/media");
      },
      async upload(file, title, assetType = "Product Asset") {
        const formData = new FormData();
        formData.append("file", file);
        if (title) formData.append("title", title);
        formData.append("asset_type", assetType);

        const token = getAuthToken();
        const headers = token ? { "Authorization": `Bearer ${token}` } : {};

        const res = await fetch(`${API_CONFIG.BASE_URL}/api/media/upload`, {
          method: "POST",
          headers,
          body: formData
        });
        if (!res.ok) throw new Error("Upload failed");
        return await res.json();
      },
      async delete(filename) {
        return await request(`/api/media/${filename}`, { method: "DELETE" });
      }
    },

    // Dashboard
    dashboard: {
      async getStats() {
        return await request("/api/dashboard/stats");
      }
    },

    // Database Backup & Restore
    backup: {
      async export() {
        return await request("/api/backup/export");
      },
      async import(jsonData) {
        const body = typeof jsonData === "string" ? JSON.parse(jsonData) : jsonData;
        return await request("/api/backup/import", { method: "POST", body });
      },
      async reset() {
        return await request("/api/backup/reset", { method: "POST" });
      }
    },

    // =========================================================================
    // Customer Authentication & Account (storefront-facing)
    // =========================================================================
    customer: {
      /** Initiate signup: send OTP to email */
      async signupInitiate(name, email) {
        return await request("/api/customer/auth/signup/initiate", {
          method: "POST", body: { name, email }
        });
      },
      /** Resend OTP */
      async signupResendOtp(email) {
        return await request("/api/customer/auth/signup/resend-otp", {
          method: "POST", body: { email }
        });
      },
      /** Verify OTP — returns signup_token */
      async signupVerifyOtp(email, otp) {
        return await request("/api/customer/auth/signup/verify-otp", {
          method: "POST", body: { email, otp }
        });
      },
      /** Complete signup with password */
      async signupComplete(email, signup_token, password, confirm_password) {
        const res = await request("/api/customer/auth/signup/complete", {
          method: "POST", body: { email, signup_token, password, confirm_password }
        });
        if (res && res.token) {
          localStorage.setItem(API_CONFIG.STORAGE_CUSTOMER_KEY, JSON.stringify({
            id: res.user && res.user.id,
            name: res.user && res.user.name,
            email: res.user && res.user.email,
            token: res.token
          }));
        }
        return res;
      },
      /**
       * Log in a customer.
       * Stores the JWT in localStorage so subsequent API calls (including
       * createRazorpayOrder) automatically include the customer identity.
       */
      async login(email, password, remember_me = false) {
        const res = await request("/api/customer/auth/login", {
          method: "POST", body: { email, password, remember_me }
        });
        if (res && res.token) {
          const sessionData = {
            id: res.user && res.user.id,
            name: res.user && res.user.name,
            email: res.user && res.user.email,
            token: res.token
          };
          if (remember_me) {
            localStorage.setItem(API_CONFIG.STORAGE_CUSTOMER_KEY, JSON.stringify(sessionData));
          } else {
            sessionStorage.setItem(API_CONFIG.STORAGE_CUSTOMER_KEY, JSON.stringify(sessionData));
          }
        }
        return res;
      },
      /** Get current customer profile */
      async me() {
        return await request("/api/customer/auth/me");
      },
      /** Log out current customer and clear stored session */
      async logout() {
        try {
          await request("/api/customer/auth/logout", { method: "POST" });
        } catch (e) { /* ignore network errors on logout */ }
        localStorage.removeItem(API_CONFIG.STORAGE_CUSTOMER_KEY);
        sessionStorage.removeItem(API_CONFIG.STORAGE_CUSTOMER_KEY);
        return { success: true };
      },
      /** Get authenticated customer profile */
      async getProfile() {
        return await request("/api/customer/profile");
      },
      /** Update authenticated customer profile */
      async updateProfile(updates) {
        return await request("/api/customer/profile", { method: "PUT", body: updates });
      },
      /**
       * Fetch all orders for the currently logged-in customer.
       * SOURCE OF TRUTH: fetches from MongoDB via the backend.
       * Never use localStorage as the primary order store.
       * Call this after login, page load, and after successful checkout.
       */
      async getMyOrders() {
        return await request("/api/customer/orders");
      },
      /** Forgot password */
      async forgotPassword(email) {
        return await request("/api/customer/auth/forgot-password", {
          method: "POST", body: { email }
        });
      },
      /** Verify reset token */
      async verifyResetToken(token, email) {
        return await request(`/api/customer/auth/verify-reset-token?token=${encodeURIComponent(token)}&email=${encodeURIComponent(email)}`);
      },
      /** Complete password reset */
      async resetPassword(token, email, new_password, confirm_password) {
        return await request("/api/customer/auth/reset-password", {
          method: "POST", body: { token, email, new_password, confirm_password }
        });
      }
    },

    // Full LocalStore Bootstrapper & Synchronizer
    // Pulls all data from backend API and writes into local DazzleStore / localStorage
    async syncFromBackend() {
      try {
        const exportData = await request("/api/backup/export");
        if (exportData && window.DazzleStore && typeof window.DazzleStore.importAll === "function") {
          window.DazzleStore.importAll(JSON.stringify(exportData));
          console.log("? DazzleStore successfully synchronized with backend database!");
          return true;
        }
      } catch (e) {
        console.warn("Unable to sync from backend, using current local cache:", e);
      }
      return false;
    }
  };

  return api;
});
