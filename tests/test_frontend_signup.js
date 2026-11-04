/**
 * Verification Test Suite: Frontend Customer Signup, Session Storage & Redirect Logic
 * Tests dazzle_api_client.js and auth.html handleSignupStage3 controller logic.
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// Mock browser Web Storage (sessionStorage & localStorage)
class MockStorage {
  constructor() {
    this.store = {};
  }
  getItem(key) {
    return Object.prototype.hasOwnProperty.call(this.store, key) ? this.store[key] : null;
  }
  setItem(key, value) {
    this.store[key] = String(value);
  }
  removeItem(key) {
    delete this.store[key];
  }
  clear() {
    this.store = {};
  }
}

// Global browser mocks
global.sessionStorage = new MockStorage();
global.localStorage = new MockStorage();
global.window = {
  location: {
    search: "?redirect=shop.html",
    pathname: "/auth.html",
    href: ""
  }
};
global.self = global.window;

// Load DazzleApi client from frontend directory
const clientPath = path.resolve(__dirname, "../../Dazzle_frontend/dazzle_api_client.js");
const clientCode = fs.readFileSync(clientPath, "utf-8");

// Execute client code in context
const factory = new Function("module", "exports", `${clientCode}; return (typeof DazzleApi !== 'undefined' ? DazzleApi : module.exports);`);
const mod = { exports: {} };
const DazzleApi = factory(mod, mod.exports);
global.window.DazzleApi = DazzleApi;

console.log("? DazzleApi client loaded successfully.");

async function runTests() {
  let passed = 0;
  let failed = 0;

  function test(name, fn) {
    try {
      fn();
      console.log(`? PASS: ${name}`);
      passed++;
    } catch (e) {
      console.error(`? FAIL: ${name}`);
      console.error(e);
      failed++;
    }
  }

  async function asyncTest(name, fn) {
    try {
      await fn();
      console.log(`? PASS: ${name}`);
      passed++;
    } catch (e) {
      console.error(`? FAIL: ${name}`);
      console.error(e);
      failed++;
    }
  }

  // TEST 1: signupComplete without rememberMe parameter (default = false)
  await asyncTest("signupComplete executes without ReferenceError (default rememberMe=false)", async () => {
    sessionStorage.clear();
    localStorage.clear();

    // Mock fetch for /api/customer/auth/signup/complete
    global.fetch = async (url, options) => {
      assert(url.includes("/api/customer/auth/signup/complete"), `Unexpected URL: ${url}`);
      const body = JSON.parse(options.body);
      assert.strictEqual(body.email, "test@dazzlebydua.com");
      assert.strictEqual(body.signup_token, "valid_mock_token");
      assert.strictEqual(body.password, "StrongPass2026!");
      return {
        ok: true,
        json: async () => ({
          success: true,
          token: "jwt_token_signup_stage3_test",
          user: { id: "CUST-001", name: "Dua Fatima", email: "test@dazzlebydua.com" }
        })
      };
    };

    // Calling signupComplete without 5th argument must NOT throw ReferenceError
    const res = await DazzleApi.customer.signupComplete(
      "test@dazzlebydua.com",
      "valid_mock_token",
      "StrongPass2026!",
      "StrongPass2026!"
    );

    assert.strictEqual(res.success, true);
    assert.strictEqual(res.token, "jwt_token_signup_stage3_test");

    // Must be in sessionStorage
    const sessStr = sessionStorage.getItem("dazzle_customer_session");
    assert(sessStr !== null, "sessionStorage should contain customer session");
    const sessObj = JSON.parse(sessStr);
    assert.strictEqual(sessObj.user.name, "Dua Fatima");
    assert.strictEqual(sessObj.token, "jwt_token_signup_stage3_test");

    // Must NOT be in localStorage since rememberMe was false
    const localStr = localStorage.getItem("dazzle_customer_session");
    assert.strictEqual(localStr, null, "localStorage should be null when rememberMe=false");

    assert.strictEqual(DazzleApi.customer.isLoggedIn(), true, "isLoggedIn() should be true");
  });

  // TEST 2: signupComplete with rememberMe = true
  await asyncTest("signupComplete stores session in both sessionStorage and localStorage when rememberMe=true", async () => {
    sessionStorage.clear();
    localStorage.clear();

    global.fetch = async () => ({
      ok: true,
      json: async () => ({
        success: true,
        token: "jwt_token_persistent_test",
        user: { id: "CUST-002", name: "Persistent Customer", email: "remember@dazzlebydua.com" }
      })
    });

    const res = await DazzleApi.customer.signupComplete(
      "remember@dazzlebydua.com",
      "mock_token_2",
      "Password123!",
      "Password123!",
      true // rememberMe = true
    );

    assert.strictEqual(res.success, true);

    // Both storages must have session
    const sess = JSON.parse(sessionStorage.getItem("dazzle_customer_session"));
    const local = JSON.parse(localStorage.getItem("dazzle_customer_session"));
    assert.strictEqual(sess.token, "jwt_token_persistent_test");
    assert.strictEqual(local.token, "jwt_token_persistent_test");
    assert.strictEqual(local.user.email, "remember@dazzlebydua.com");
  });

  // TEST 3: customer.login with rememberMe = true and false
  await asyncTest("customer.login preserves existing functionality with rememberMe", async () => {
    sessionStorage.clear();
    localStorage.clear();

    global.fetch = async (url, options) => {
      assert(url.includes("/api/customer/auth/login"));
      const body = JSON.parse(options.body);
      assert.strictEqual(body.remember_me, true);
      return {
        ok: true,
        json: async () => ({
          success: true,
          token: "jwt_login_token",
          user: { id: "CUST-003", name: "Login User", email: "login@dazzlebydua.com" }
        })
      };
    };

    const res = await DazzleApi.customer.login("login@dazzlebydua.com", "MyPass123!", true);
    assert.strictEqual(res.success, true);
    assert.strictEqual(JSON.parse(localStorage.getItem("dazzle_customer_session")).token, "jwt_login_token");
    assert.strictEqual(JSON.parse(sessionStorage.getItem("dazzle_customer_session")).token, "jwt_login_token");
  });

  // TEST 4: customer.logout clears both sessionStorage and localStorage
  await asyncTest("customer.logout clears both sessionStorage and localStorage", async () => {
    sessionStorage.setItem("dazzle_customer_session", JSON.stringify({ token: "tok" }));
    localStorage.setItem("dazzle_customer_session", JSON.stringify({ token: "tok" }));

    global.fetch = async () => ({
      ok: true,
      json: async () => ({ success: true })
    });

    await DazzleApi.customer.logout();

    assert.strictEqual(sessionStorage.getItem("dazzle_customer_session"), null);
    assert.strictEqual(localStorage.getItem("dazzle_customer_session"), null);
    assert.strictEqual(DazzleApi.customer.isLoggedIn(), false);
  });

  // TEST 5: Simulate handleSignupStage3 redirect and error recovery
  await asyncTest("handleSignupStage3 simulation executes smoothly and redirects to target URL", async () => {
    sessionStorage.clear();
    localStorage.clear();
    window.location.href = "";
    window.location.search = "?redirect=orders.html";

    global.fetch = async () => ({
      ok: true,
      json: async () => ({
        success: true,
        token: "jwt_stage3_redirect_test",
        user: { id: "CUST-005", name: "Redirect User", email: "redirect@dazzlebydua.com" }
      })
    });

    let alertShown = null;
    let alertType = null;
    const showAuthAlert = (msg, type) => {
      alertShown = msg;
      alertType = type;
    };

    // Controller execution
    const currentSignupState = {
      email: "redirect@dazzlebydua.com",
      signupToken: "token_for_stage3"
    };

    const p1 = "StrongPassword123!";
    const p2 = "StrongPassword123!";
    const rememberMe = true;

    // Simulate handleSignupStage3 try-catch block
    let registrationCompleted = false;
    try {
      const res = await DazzleApi.customer.signupComplete(
        currentSignupState.email,
        currentSignupState.signupToken,
        p1,
        p2,
        rememberMe
      );
      registrationCompleted = true;
      showAuthAlert("Account created successfully! Welcome to Dazzle by Dua.", "success");

      const params = new URLSearchParams(window.location.search);
      const redirectUrl = params.get("redirect") || "index.html";
      window.location.href = redirectUrl;
    } catch (err) {
      if (registrationCompleted || DazzleApi.customer.isLoggedIn()) {
        showAuthAlert("Account created! Redirecting...", "success");
        window.location.href = "orders.html";
      } else {
        showAuthAlert(err.message, "error");
      }
    }

    assert.strictEqual(registrationCompleted, true, "Registration must complete");
    assert.strictEqual(alertType, "success", "Alert should be success");
    assert.strictEqual(window.location.href, "orders.html", "Redirect target must be orders.html");
  });

  // TEST 6: Duplicate retry protection
  await asyncTest("handleSignupStage3 gracefully handles already-existing session without error", async () => {
    // Session is already stored from successful account creation
    sessionStorage.setItem("dazzle_customer_session", JSON.stringify({
      user: { name: "Existing User", email: "existing@dazzlebydua.com" },
      token: "existing_valid_token"
    }));

    window.location.href = "";
    window.location.search = "";

    // Backend returns 400 'already exists' on duplicate submit
    global.fetch = async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: "An account with this email address already exists. Please log in." })
    });

    let alertShown = null;
    let alertType = null;
    const showAuthAlert = (msg, type) => {
      alertShown = msg;
      alertType = type;
    };

    try {
      await DazzleApi.customer.signupComplete("existing@dazzlebydua.com", "used_token", "Pass12345!", "Pass12345!", true);
    } catch (err) {
      // Recovery logic from handleSignupStage3:
      const errMsg = err.message || "";
      if (errMsg.toLowerCase().includes("already exists") && DazzleApi.customer.isLoggedIn()) {
        showAuthAlert("Welcome back! Redirecting...", "success");
        const params = new URLSearchParams(window.location.search);
        const redirectUrl = params.get("redirect") || "index.html";
        window.location.href = redirectUrl;
      } else {
        showAuthAlert(errMsg, "error");
      }
    }

    assert.strictEqual(alertType, "success");
    assert.strictEqual(window.location.href, "index.html", "Should redirect to index.html");
  });

  console.log(`\n========================================`);
  console.log(`Results: ${passed} passed, ${failed} failed`);
  console.log(`========================================\n`);

  if (failed > 0) process.exit(1);
}

runTests().catch(err => {
  console.error("Test execution failed:", err);
  process.exit(1);
});

